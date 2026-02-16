import elephantq

@elephantq.job()
async def daily_report():
    return "ok"

elephantq.schedule("0 9 * * *").job(daily_report)
elephantq.every("10m").do(daily_report)
