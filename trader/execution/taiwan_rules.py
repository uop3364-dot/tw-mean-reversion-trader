import math
class TaiwanTickRule:
    @staticmethod
    def tick(price):
        if price<10:return .01
        if price<50:return .05
        if price<100:return .1
        if price<500:return .5
        if price<1000:return 1.
        return 5.
    @classmethod
    def round_down(cls,price):
        t=cls.tick(price);return round(math.floor(price/t+1e-10)*t,2)
    @classmethod
    def round_up(cls,price):
        t=cls.tick(price);return round(math.ceil(price/t-1e-10)*t,2)
    @classmethod
    def limit_up(cls,previous_close):return cls.round_down(previous_close*1.10)
    @classmethod
    def limit_down(cls,previous_close):return cls.round_up(previous_close*.90)
