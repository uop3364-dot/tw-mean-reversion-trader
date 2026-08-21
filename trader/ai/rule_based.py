from .base import RiskAnalyzer,RiskAssessment
class RuleBasedRiskAnalyzer(RiskAnalyzer):
    def analyze(self,symbol,context):
        score=float(context.get("regime_risk_score",100));return RiskAssessment(score,score<=40,"regime rules")
