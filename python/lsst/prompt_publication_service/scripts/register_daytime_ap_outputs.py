import asyncio

import click

from lsst.daf.butler import Butler

from ..configs.prompt_processing_outputs import PROMPT_PROCESSING_OUTPUT_CONFIG
from ..database import Database
from ..register_daytime_ap import register_daytime_ap_output


@click.command()
@click.argument("butler_repo")
@click.argument("database_uri")
@click.argument("day_obs", type=int)
@click.argument("collection")
def register_daytime_ap_output_cli(
    butler_repo: str, database_uri: str, day_obs: int, collection: str
) -> None:
    """Register daytime AP outputs from the given collection for the given
    dayobs.  This resets the list of datasets for publication on that
    dayobs to the "find-first" datasets in the given collection.
    """
    with Butler.from_config(butler_repo) as butler:
        asyncio.run(_register(butler, database_uri, day_obs, collection))


async def _register(butler: Butler, database_uri: str, day_obs: int, collection: str) -> None:
    async with Database(database_uri) as db:
        await register_daytime_ap_output(db, butler, PROMPT_PROCESSING_OUTPUT_CONFIG, day_obs, collection)


if __name__ == "__main__":
    register_daytime_ap_output_cli()
