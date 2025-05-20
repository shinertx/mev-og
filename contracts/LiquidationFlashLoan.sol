// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

/**
 * @title LiquidationFlashLoan
 * @notice Executes atomic liquidations using Aave V3 flash loans. Supports
 *         single and batch liquidations with slippage controlled swaps.
 * @dev Swaps are performed through external swapper contracts which must return
 *      the amount of tokens received. This contract is optimized for gas and
 *      includes a circuit breaker for abnormal conditions.
 */
contract LiquidationFlashLoan is Ownable, ReentrancyGuard {
    /// @notice Aave V3 Pool address.
    address public immutable POOL;

    /// @notice Minimum profit required for a liquidation (in debt asset units).
    uint256 public minProfit;

    /// @notice Maximum allowed gas price for initiating a liquidation.
    uint256 public gasPriceLimit;

    /// @notice Number of consecutive failures recorded.
    uint256 public failureCount;

    /// @notice Consecutive failure threshold before circuit breaker trips.
    uint256 public failureThreshold;

    /**
     * @notice Parameters describing a liquidation operation.
     * @param borrower Address of the account to liquidate.
     * @param collateralAsset Asset to seize from the borrower.
     * @param debtToCover Amount of debt to repay for the borrower.
     * @param slippageBps Maximum acceptable slippage in basis points for swap.
     * @param swapper Address of the external swapper.
     * @param swapData Calldata to pass to the swapper.
     */
    struct LiquidationParams {
        address borrower;
        address collateralAsset;
        uint256 debtToCover;
        uint256 slippageBps;
        address swapper;
        bytes swapData;
    }

    /// @notice Emitted when a flash loan is initiated.
    event FlashLoanStarted(address indexed asset, uint256 amount);

    /// @notice Emitted when a liquidation succeeds.
    event LiquidationSuccessful(
        address indexed borrower,
        address indexed collateralAsset,
        address indexed debtAsset,
        uint256 profit
    );

    /// @notice Emitted after a collateral swap.
    event SwapSuccessful(
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 amountIn,
        uint256 amountOut
    );

    /// @notice Emitted once the flash loan is fully repaid.
    event FlashLoanRepaid(address indexed asset, uint256 amount);

    /**
     * @param pool            Address of the Aave V3 Pool.
     * @param _minProfit      Initial minimum profit threshold in debt units.
     * @param _gasPriceLimit  Maximum gas price allowed for liquidations.
     * @param _failureThres   Number of consecutive failures before halt.
     */
    constructor(
        address pool,
        uint256 _minProfit,
        uint256 _gasPriceLimit,
        uint256 _failureThres
    ) {
        require(pool != address(0), "pool zero");
        POOL = pool;
        minProfit = _minProfit;
        gasPriceLimit = _gasPriceLimit;
        failureThreshold = _failureThres;
    }

    /**
     * @notice Updates the minimum profit threshold.
     * @param newMinProfit The new profit threshold in debt asset units.
     */
    function setMinProfit(uint256 newMinProfit) external onlyOwner {
        minProfit = newMinProfit;
    }

    /**
     * @notice Updates the gas price limit used by the circuit breaker.
     * @param newLimit New maximum gas price permitted.
     */
    function setGasPriceLimit(uint256 newLimit) external onlyOwner {
        gasPriceLimit = newLimit;
    }

    /**
     * @notice Updates the failure threshold for the circuit breaker.
     * @param newThreshold Number of consecutive failures allowed.
     */
    function setFailureThreshold(uint256 newThreshold) external onlyOwner {
        failureThreshold = newThreshold;
    }

    /**
     * @notice Allows the owner to withdraw any ERC20 tokens stuck in the contract.
     * @param token The address of the token to withdraw.
     * @param to The recipient of the withdrawn tokens.
     * @param amount The amount to withdraw.
     */
    function emergencyWithdraw(address token, address to, uint256 amount) external onlyOwner {
        require(to != address(0), "zero to");
        IERC20(token).transfer(to, amount);
    }

    // ---------------------------------------------------------------------
    // Flash loan and liquidation logic
    // ---------------------------------------------------------------------

    /**
     * @notice Initiates a single liquidation via flash loan.
     * @param asset Debt asset to borrow from Aave.
     * @param amount Amount of the debt asset to borrow.
     * @param borrower Address of borrower to liquidate.
     * @param collateralAsset Collateral to seize from the borrower.
     * @param slippageBps Maximum slippage tolerated for the swap.
     * @param swapper Address of the swapper contract.
     * @param swapData Calldata for the swapper.
     */
    function initiateLiquidation(
        address asset,
        uint256 amount,
        address borrower,
        address collateralAsset,
        uint256 slippageBps,
        address swapper,
        bytes calldata swapData
    ) external nonReentrant {
        LiquidationParams[] memory ops = new LiquidationParams[](1);
        ops[0] = LiquidationParams(borrower, collateralAsset, amount, slippageBps, swapper, swapData);
        _initiateLiquidations(asset, ops);
    }

    /**
     * @notice Initiates batch liquidations via a single flash loan.
     * @param asset Debt asset to borrow from Aave.
     * @param ops Array describing each liquidation to perform.
     */
    function initiateBatchLiquidation(address asset, LiquidationParams[] calldata ops) external nonReentrant {
        _initiateLiquidations(asset, ops);
    }

    /// @dev Internal helper to start the flash loan process.
    function _initiateLiquidations(address asset, LiquidationParams[] calldata ops) internal {
        require(tx.gasprice <= gasPriceLimit, "gas price too high");
        require(failureCount < failureThreshold, "circuit breaker tripped");

        uint256 totalAmount;
        for (uint256 i; i < ops.length; ) {
            totalAmount += ops[i].debtToCover;
            unchecked { ++i; }
        }

        bytes memory params = abi.encode(ops);
        emit FlashLoanStarted(asset, totalAmount);
        IPool(POOL).flashLoanSimple(address(this), asset, totalAmount, params, 0);
    }

    /**
     * @notice Aave flash loan callback executed after receiving the flash loan.
     * @dev Performs each liquidation, swaps collateral and repays the flash loan.
     * @param asset The borrowed debt asset.
     * @param amount Amount borrowed.
     * @param premium Premium owed to Aave.
     * @param params ABI-encoded array of {LiquidationParams}.
     * @return Always returns true on success.
     */
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address, /* initiator */
        bytes calldata params
    ) external returns (bool) {
        require(msg.sender == POOL, "caller not pool");

        LiquidationParams[] memory ops = abi.decode(params, (LiquidationParams[]));
        uint256 totalReceived;
        for (uint256 i; i < ops.length; ) {
            LiquidationParams memory op = ops[i];
            try IPool(POOL).liquidationCall(op.collateralAsset, asset, op.borrower, op.debtToCover, false) {
                uint256 collBal = IERC20(op.collateralAsset).balanceOf(address(this));
                require(collBal > 0, "no collateral");
                IERC20(op.collateralAsset).approve(op.swapper, collBal);
                uint256 minOut = (collBal * (10_000 - op.slippageBps)) / 10_000;
                (bool success, bytes memory result) = op.swapper.call(op.swapData);
                require(success, "swap failed");
                uint256 received = abi.decode(result, (uint256));
                require(received >= minOut, "slippage too high");
                emit SwapSuccessful(op.collateralAsset, asset, collBal, received);
                emit LiquidationSuccessful(op.borrower, op.collateralAsset, asset, received - op.debtToCover);
                totalReceived += received;
            } catch {
                unchecked { ++failureCount; }
                revert("liquidation failed");
            }
            unchecked { ++i; }
        }

        failureCount = 0; // reset on success
        uint256 totalDebt = amount + premium;
        require(totalReceived >= totalDebt + minProfit, "insufficient profit");
        IERC20(asset).approve(POOL, totalDebt);
        emit FlashLoanRepaid(asset, totalDebt);
        return true;
    }
}

interface IPool {
    function flashLoanSimple(
        address receiverAddress,
        address asset,
        uint256 amount,
        bytes calldata params,
        uint16 referralCode
    ) external;

    function liquidationCall(
        address collateral,
        address debt,
        address user,
        uint256 debtToCover,
        bool receiveAToken
    ) external;
}

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);

    function balanceOf(address account) external view returns (uint256);

    function approve(address spender, uint256 amount) external returns (bool);
}
