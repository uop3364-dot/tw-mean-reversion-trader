from .base import RiskAnalyzer,RiskAssessment
class NullRiskAnalyzer(RiskAnalyzer):
    def analyze(self,symbol,context):return RiskAssessment(0,True,"not evaluated")
