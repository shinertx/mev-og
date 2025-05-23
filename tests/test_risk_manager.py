import asyncio
import unittest
from unittest.mock import patch
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from risk_manager import RiskManager, RiskThresholds


class RiskManagerTests(unittest.TestCase):
    def setUp(self):
        thresholds = RiskThresholds(pnl=10, slippage=1, gas_cost=5, latency=1)
        self.manager = RiskManager(thresholds, webhook_url="http://example")

    def test_kill_switch_sets_flag_and_posts_webhook(self):
        with patch.object(self.manager, "_post_webhook") as post_webhook, \
             patch.object(self.manager, "_send_email_alert"), \
             patch.object(self.manager, "_post_slack_alert"):
            asyncio.run(self.manager.kill_switch())
            self.assertTrue(self.manager.killed)
            post_webhook.assert_called_once_with({"event": "kill_switch"})

    def test_update_metrics_triggers_kill_switch(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def dummy():
            self.manager.killed = True

        with patch("asyncio.create_task", side_effect=lambda coro: loop.run_until_complete(coro)):
            with patch.object(self.manager, "kill_switch", dummy):
                self.manager.update_metrics(pnl=20, slippage=0, gas_cost=0, latency=0)
                self.assertTrue(self.manager.killed)
        loop.close()


if __name__ == "__main__":
    unittest.main()
