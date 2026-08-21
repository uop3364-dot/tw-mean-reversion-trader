from dataclasses import dataclass
from abc import ABC,abstractmethod
@dataclass
class RiskAssessment:
    score:float; approved:bool; reason:str
class RiskAnalyzer(ABC):
    @abstractmethod
    def analyze(self,symbol,context)->RiskAssessment:...
