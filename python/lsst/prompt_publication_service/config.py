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

from collections import defaultdict
from typing import Callable, Literal, NamedTuple


class DatasetTypeConfigurationItem(NamedTuple):
    embargo_period_hours: int
    """How long we have to wait after the image was taken, in hours, before
    this dataset can be copied out of the embargo rack.
    """
    publish_to_public: bool
    """If `True`, this dataset will be published to the user-facing Butler
    repositories at Google.  If `False`, it will only be available internally
    at USDF.
    """
    retention_period_days: int | Literal["forever"]
    """How long, in days, we keep the dataset after it is unembargoed or
    published."""


class ConfigurationGroup[_T](NamedTuple):
    key: _T
    dataset_types: list[str]


class DatasetTypeConfiguration:
    def __init__(self, config: dict[str, DatasetTypeConfigurationItem]):
        self._config = dict(config)

    def group_by[_T](
        self, key_func: Callable[[DatasetTypeConfigurationItem], _T]
    ) -> list[ConfigurationGroup[_T]]:
        groups: defaultdict[_T, set] = defaultdict(set)
        for dataset_type, config in self._config.items():
            key = key_func(config)
            groups[key].add(dataset_type)
        return [ConfigurationGroup(key, sorted(dataset_types)) for key, dataset_types in groups.items()]
