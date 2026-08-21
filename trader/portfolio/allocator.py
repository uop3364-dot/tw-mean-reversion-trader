import math
def allocate(net_asset,available_cash,remaining_slots,price,max_weight=.15):
    if available_cash<=0 or remaining_slots<=0 or price<=0:return 0
    target=min(net_asset*max_weight,available_cash/remaining_slots)
    return max(0,math.floor(target/price))

