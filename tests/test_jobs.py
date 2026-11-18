import asyncio

from app.jobs import periodic


def test_periodisch_und_robust():
    calls = []

    def job():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("erster Lauf scheitert")

    async def run():
        async with periodic(0.01, job, "Test"):
            await asyncio.sleep(0.05)
        count = len(calls)
        await asyncio.sleep(0.03)
        return count

    count = asyncio.run(run())
    assert count >= 2 and len(calls) == count                       # läuft weiter trotz Fehler, endet sauber
