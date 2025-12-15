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

from ..config import DatasetTypeConfiguration, DatasetTypeConfigurationItem

_EMBARGO_PERIOD_HOURS = 80
_TIER2_RETENTION_PERIOD_DAYS = 30

_PROVENANCE = DatasetTypeConfigurationItem(
    embargo_period_hours=0, publish_to_public=True, retention_period_days="forever"
)

_TIER1_PIXEL = DatasetTypeConfigurationItem(
    embargo_period_hours=_EMBARGO_PERIOD_HOURS, publish_to_public=True, retention_period_days="forever"
)

_TIER1_NONPIXEL = DatasetTypeConfigurationItem(
    embargo_period_hours=0, publish_to_public=True, retention_period_days="forever"
)

_TIER2_PIXEL = DatasetTypeConfigurationItem(
    embargo_period_hours=_EMBARGO_PERIOD_HOURS,
    publish_to_public=True,
    retention_period_days=_TIER2_RETENTION_PERIOD_DAYS,
)

_TIER2_NONPIXEL = DatasetTypeConfigurationItem(
    embargo_period_hours=0, publish_to_public=True, retention_period_days=_TIER2_RETENTION_PERIOD_DAYS
)

_USDF_INTERNAL_NONPIXEL = DatasetTypeConfigurationItem(
    embargo_period_hours=0, publish_to_public=False, retention_period_days=_TIER2_RETENTION_PERIOD_DAYS
)


# This configuration is from RFC-1134.
PROMPT_PROCESSING_OUTPUT_CONFIG = DatasetTypeConfiguration(
    {
        # Tier 1
        "preliminary_visit_image": _TIER1_PIXEL,
        "preliminary_visit_image_background": _TIER1_PIXEL,
        "difference_kernel": _TIER1_NONPIXEL,
        "template_detector": _TIER1_PIXEL,
        # Tier 2
        "difference_image": _TIER2_PIXEL,
        "single_visit_star_footprints": _TIER2_NONPIXEL,
        "dia_source_apdb": _TIER2_NONPIXEL,
        "dia_forced_source_apdb": _TIER2_NONPIXEL,
        "dia_object_apdb": _TIER2_NONPIXEL,
        "marginal_new_dia_source": _TIER2_NONPIXEL,
        "ss_source_direct_detector": _TIER2_NONPIXEL,
        "ss_object_direct_unassociated": _TIER2_NONPIXEL,
        "ss_object_unassociated_detector": _TIER2_NONPIXEL,
        "ss_source_detector": _TIER2_NONPIXEL,
        "regionTimeInfo": _TIER2_NONPIXEL,
        # Non-public
        "dia_source_detector": _USDF_INTERNAL_NONPIXEL,
        "dia_source_schema": _USDF_INTERNAL_NONPIXEL,
        "dia_source_unfiltered": _USDF_INTERNAL_NONPIXEL,
        "new_dia_source": _USDF_INTERNAL_NONPIXEL,
        "preloaded_dia_forced_source": _USDF_INTERNAL_NONPIXEL,
        "preloaded_dia_object": _USDF_INTERNAL_NONPIXEL,
        "preloaded_dia_source": _USDF_INTERNAL_NONPIXEL,
        "preloaded_ss_object": _USDF_INTERNAL_NONPIXEL,
        "single_visit_star_schema": _USDF_INTERNAL_NONPIXEL,
        # Miscellaneous provenance datasets (config/log/metadata/packages).
        "analyzeAssociateDiaSourceTiming_config": _PROVENANCE,
        "analyzeAssociateDiaSourceTiming_log": _PROVENANCE,
        "analyzeAssociateDiaSourceTiming_metadata": _PROVENANCE,
        "analyzeAssociatedDiaSourceTable_config": _PROVENANCE,
        "analyzeAssociatedDiaSourceTable_log": _PROVENANCE,
        "analyzeAssociatedDiaSourceTable_metadata": _PROVENANCE,
        "analyzeAssociatedDirectSolarSystemObjectTable_config": _PROVENANCE,
        "analyzeAssociatedDirectSolarSystemObjectTable_log": _PROVENANCE,
        "analyzeAssociatedDirectSolarSystemObjectTable_metadata": _PROVENANCE,
        "analyzeDiaSourceAssociationMetrics_config": _PROVENANCE,
        "analyzeDiaSourceAssociationMetrics_log": _PROVENANCE,
        "analyzeDiaSourceAssociationMetrics_metadata": _PROVENANCE,
        "analyzeDiaSourceDetectionMetrics_config": _PROVENANCE,
        "analyzeDiaSourceDetectionMetrics_log": _PROVENANCE,
        "analyzeDiaSourceDetectionMetrics_metadata": _PROVENANCE,
        "analyzeImageDifferenceMetrics_config": _PROVENANCE,
        "analyzeImageDifferenceMetrics_log": _PROVENANCE,
        "analyzeImageDifferenceMetrics_metadata": _PROVENANCE,
        "analyzeLoadDiaCatalogsMetrics_config": _PROVENANCE,
        "analyzeLoadDiaCatalogsMetrics_log": _PROVENANCE,
        "analyzeLoadDiaCatalogsMetrics_metadata": _PROVENANCE,
        "analyzePreliminarySummaryStats_config": _PROVENANCE,
        "analyzePreliminarySummaryStats_log": _PROVENANCE,
        "analyzePreliminarySummaryStats_metadata": _PROVENANCE,
        "analyzeTrailedDiaSourceTable_config": _PROVENANCE,
        "analyzeTrailedDiaSourceTable_log": _PROVENANCE,
        "analyzeTrailedDiaSourceTable_metadata": _PROVENANCE,
        "analyzeUnassociatedDirectSolarSystemObjectTable_config": _PROVENANCE,
        "analyzeUnassociatedDirectSolarSystemObjectTable_log": _PROVENANCE,
        "analyzeUnassociatedDirectSolarSystemObjectTable_metadata": _PROVENANCE,
        "associateApdb_config": _PROVENANCE,
        "associateApdb_log": _PROVENANCE,
        "associateApdb_metadata": _PROVENANCE,
        "associateSolarSystemDirectSource_config": _PROVENANCE,
        "associateSolarSystemDirectSource_log": _PROVENANCE,
        "associateSolarSystemDirectSource_metadata": _PROVENANCE,
        "buildTemplate_config": _PROVENANCE,
        "buildTemplate_log": _PROVENANCE,
        "buildTemplate_metadata": _PROVENANCE,
        "calibrateImage_config": _PROVENANCE,
        "calibrateImage_log": _PROVENANCE,
        "calibrateImage_metadata": _PROVENANCE,
        "computeReliability_config": _PROVENANCE,
        "computeReliability_log": _PROVENANCE,
        "computeReliability_metadata": _PROVENANCE,
        "detectAndMeasureDiaSource_config": _PROVENANCE,
        "detectAndMeasureDiaSource_log": _PROVENANCE,
        "detectAndMeasureDiaSource_metadata": _PROVENANCE,
        "filterDiaSourcePostReliability_config": _PROVENANCE,
        "filterDiaSourcePostReliability_log": _PROVENANCE,
        "filterDiaSourcePostReliability_metadata": _PROVENANCE,
        "filterDiaSource_config": _PROVENANCE,
        "filterDiaSource_log": _PROVENANCE,
        "filterDiaSource_metadata": _PROVENANCE,
        "isr_config": _PROVENANCE,
        "isr_log": _PROVENANCE,
        "isr_metadata": _PROVENANCE,
        "loadDiaCatalogs_config": _PROVENANCE,
        "loadDiaCatalogs_log": _PROVENANCE,
        "loadDiaCatalogs_metadata": _PROVENANCE,
        "mpSkyEphemerisQuery_config": _PROVENANCE,
        "mpSkyEphemerisQuery_log": _PROVENANCE,
        "mpSkyEphemerisQuery_metadata": _PROVENANCE,
        "packages": _PROVENANCE,
        "singleFrameDetectAndMeasure_config": _PROVENANCE,
        "singleFrameDetectAndMeasure_log": _PROVENANCE,
        "singleFrameDetectAndMeasure_metadata": _PROVENANCE,
        "standardizeDiaSource_config": _PROVENANCE,
        "standardizeDiaSource_log": _PROVENANCE,
        "standardizeDiaSource_metadata": _PROVENANCE,
        "subtractImages_config": _PROVENANCE,
        "subtractImages_log": _PROVENANCE,
        "subtractImages_metadata": _PROVENANCE,
    }
)
