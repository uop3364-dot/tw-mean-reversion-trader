from apscheduler.schedulers.blocking import BlockingScheduler
def create_scheduler(callbacks):
    s=BlockingScheduler(timezone="Asia/Taipei")
    for name,time in {"sync":"08:30","positions":"09:05","buys":"09:15","stop_orders":"13:30","refresh":"14:10","signals":"14:30","save":"15:00","report":"15:10"}.items():
        if name in callbacks:h,m=map(int,time.split(":"));s.add_job(callbacks[name],"cron",hour=h,minute=m,id=name,replace_existing=True)
    if "monitor" in callbacks:s.add_job(callbacks["monitor"],"interval",seconds=30,id="monitor",replace_existing=True)
    return s

