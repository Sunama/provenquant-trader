"""CLI task runner — mirrors the pattern in witzh/backend/tasks.py"""
import asyncio
import typer

app = typer.Typer()


@app.command()
def migrate():
    """Run Alembic upgrade head."""
    import subprocess
    subprocess.run(["alembic", "upgrade", "head"], check=True)


@app.command()
def paper_balance():
    """Print current paper-trade balance."""
    async def run():
        from app.services.trade_adapter.paper import PaperTradeAdapter
        adapter = PaperTradeAdapter()
        bal = await adapter.get_balance()
        typer.echo(f"Paper balance: {bal:.2f} USDT")

    asyncio.run(run())


if __name__ == "__main__":
    app()
