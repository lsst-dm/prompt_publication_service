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

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Literal

from .schema import DatasetOrigin


@dataclass(frozen=True)
class DatasetTypeConfigurationItem:
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


@dataclass(frozen=True)
class ConfigurationGroup[_T]:
    key: _T
    origin: DatasetOrigin
    dataset_types: list[str]


class DatasetTypeConfiguration:
    def __init__(self, config: dict[DatasetOrigin, dict[str, DatasetTypeConfigurationItem]]):
        self._config = {k: dict(v) for k, v in config.items()}

    def subset(self, dataset_types: list[str]) -> DatasetTypeConfiguration:
        return DatasetTypeConfiguration(
            {origin: {dt: self._config[origin][dt] for dt in dataset_types} for origin in self._config.keys()}
        )

    def group_by[_T](
        self, key_func: Callable[[DatasetTypeConfigurationItem], _T]
    ) -> list[ConfigurationGroup[_T]]:
        # Computed key -> origin -> set of dataset types.
        groups: defaultdict[_T, defaultdict[DatasetOrigin, set[str]]] = defaultdict(lambda: defaultdict(set))
        for origin, origin_config in self._config.items():
            for dataset_type, config in origin_config.items():
                key = key_func(config)
                groups[key][origin].add(dataset_type)

        output = []
        for key, origin_dict in groups.items():
            for origin, dataset_types in origin_dict.items():
                output.append(ConfigurationGroup(key, origin, sorted(dataset_types)))

        return output
