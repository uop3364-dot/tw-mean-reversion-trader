from .base import RiskAnalyzer
class LLMRiskAnalyzer(RiskAnalyzer):
    def analyze(self,symbol,context):raise NotImplementedError("Optional live extension; never used by backtests")

