import click
from ..schema import Base
from sqlalchemy import create_engine


@click.command()
@click.argument("database_uri")
def initialize_db(database_uri: str):
    """Script that creates state database tables/indexes in an empty
    database.
    """
    engine = create_engine(database_uri, echo=True)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    initialize_db()
