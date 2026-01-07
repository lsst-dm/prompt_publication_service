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

"""Script used to export Butler dimension data from the embargo repository
for use in unit tests.
"""

import click

from lsst.daf.butler import Butler


@click.command()
@click.argument("repo")
@click.argument("collection")
@click.option("--where", default="")
def main(repo: str, collection: str, where: str):
    with Butler.from_config(repo) as butler:
        datasets = butler.query_all_datasets(collection, where=where)
        data_ids = set(dataset.dataId for dataset in datasets)
        with butler.export(filename="embargo_dimensions.yaml") as export:
            export.saveDataIds(data_ids)


if __name__ == "__main__":
    main()
