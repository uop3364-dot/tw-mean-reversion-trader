from dataclasses import dataclass
@dataclass(frozen=True)
class ResearchVerdict:
    verdict:str;reasons:list[str]
def evaluate(metrics,conservative,walk_forward,plateau_ok,concentration_ok,sample_ok,data_ready,bootstrap_low):
    if not data_ready:return ResearchVerdict("INVALID_DATA",["authoritative readiness failed"])
    if not sample_ok:return ResearchVerdict("INSUFFICIENT_SAMPLE",["formal sample requirement failed"])
    conditions={"OOS CAGR":metrics.get("CAGR",0)>0,"PF":metrics.get("Profit Factor",0)>1.2,"expectancy":metrics.get("Expectancy per trade",0)>0,"conservative":conservative.get("Expectancy per trade",0)>0,"walk-forward":walk_forward,"plateau":plateau_ok,"concentration":concentration_ok,"bootstrap":bootstrap_low>0}
    failed=[k for k,v in conditions.items() if not v];return ResearchVerdict("VALIDATED_CANDIDATE" if not failed else "FAILED",failed)
