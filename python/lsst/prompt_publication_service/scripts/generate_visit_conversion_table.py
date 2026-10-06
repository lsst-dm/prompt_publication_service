# This file is part of prompt_publication_service.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from itertools import batched

import click
from sqlalchemy import create_engine, text

from lsst.daf.butler import Butler, DataCoordinate


@click.command
@click.argument("butler_repo")
@click.argument("database_uri")
def generate_visit_conversion_table(butler_repo: str, database_uri: str) -> None:
    butler = Butler.from_config(butler_repo)
    engine = create_engine(database_uri)
    with engine.connect() as conn:
        results = conn.execute(
            text('SELECT DISTINCT instrument, "group" FROM dataset WHERE group IS NOT NULL')
        ).mappings()
        for batch in batched(results, 10_000):
            with butler.query() as query:
                data_coordinates = [DataCoordinate.standardize(dict(mapping)) for mapping in batch]
                dataIds = list(
                    query.join_data_coordinates(data_coordinates).data_ids(["instrument", "exposure"])
                )
                for id in dataIds:
                    print(dict(id.mapping))


if __name__ == "__main__":
    generate_visit_conversion_table()
