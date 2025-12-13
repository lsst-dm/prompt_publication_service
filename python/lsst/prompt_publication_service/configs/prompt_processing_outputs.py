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

EMBARGO_PERIOD_HOURS = 80
TIER2_RETENTION_PERIOD_DAYS = 30

PROVENANCE = DatasetTypeConfigurationItem(
    embargo_period_hours=0, publish_to_public=True, retention_period_days="forever"
)

TIER1_PIXEL = DatasetTypeConfigurationItem(
    embargo_period_hours=EMBARGO_PERIOD_HOURS, publish_to_public=True, retention_period_days="forever"
)

TIER1_NONPIXEL = DatasetTypeConfigurationItem(
    embargo_period_hours=0, publish_to_public=True, retention_period_days="forever"
)

TIER2_PIXEL = DatasetTypeConfigurationItem(
    embargo_period_hours=EMBARGO_PERIOD_HOURS,
    publish_to_public=True,
    retention_period_days=TIER2_RETENTION_PERIOD_DAYS,
)

TIER2_NONPIXEL = DatasetTypeConfigurationItem(
    embargo_period_hours=0, publish_to_public=True, retention_period_days=TIER2_RETENTION_PERIOD_DAYS
)

USDF_INTERNAL_NONPIXEL = DatasetTypeConfigurationItem(
    embargo_period_hours=0, publish_to_public=False, retention_period_days=TIER2_RETENTION_PERIOD_DAYS
)


# This configuration is from RFC-1134.
PROMPT_PROCESSING_OUTPUT_CONFIG = DatasetTypeConfiguration(
    {
        # Tier 1
        "preliminary_visit_image": TIER1_PIXEL,
        "preliminary_visit_image_background": TIER1_PIXEL,
        "difference_kernel": TIER1_NONPIXEL,
        "template_detector": TIER1_PIXEL,
        # Tier 2
        "difference_image": TIER2_PIXEL,
        "single_visit_star_footprints": TIER2_NONPIXEL,
        "dia_source_apdb": TIER2_NONPIXEL,
        "dia_forced_source_apdb": TIER2_NONPIXEL,
        "dia_object_apdb": TIER2_NONPIXEL,
        "marginal_new_dia_source": TIER2_NONPIXEL,
        "ss_source_direct_detector": TIER2_NONPIXEL,
        "ss_object_direct_unassociated": TIER2_NONPIXEL,
        "ss_object_unassociated_detector": TIER2_NONPIXEL,
        "ss_source_detector": TIER2_NONPIXEL,
        "regionTimeInfo": TIER2_NONPIXEL,
        # Non-public
        "dia_source_detector": USDF_INTERNAL_NONPIXEL,
        "dia_source_schema": USDF_INTERNAL_NONPIXEL,
        "dia_source_unfiltered": USDF_INTERNAL_NONPIXEL,
        "new_dia_source": USDF_INTERNAL_NONPIXEL,
        "preloaded_dia_forced_source": USDF_INTERNAL_NONPIXEL,
        "preloaded_dia_object": USDF_INTERNAL_NONPIXEL,
        "preloaded_dia_source": USDF_INTERNAL_NONPIXEL,
        "preloaded_ss_object": USDF_INTERNAL_NONPIXEL,
        "single_visit_star_schema": USDF_INTERNAL_NONPIXEL,
        # Miscellaneous provenance datasets (config/log/metadata/packages).
        "analyzeAssociateDiaSourceTiming_config": PROVENANCE,
        "analyzeAssociateDiaSourceTiming_log": PROVENANCE,
        "analyzeAssociateDiaSourceTiming_metadata": PROVENANCE,
        "analyzeAssociatedDiaSourceTable_config": PROVENANCE,
        "analyzeAssociatedDiaSourceTable_log": PROVENANCE,
        "analyzeAssociatedDiaSourceTable_metadata": PROVENANCE,
        "analyzeAssociatedDirectSolarSystemObjectTable_config": PROVENANCE,
        "analyzeAssociatedDirectSolarSystemObjectTable_log": PROVENANCE,
        "analyzeAssociatedDirectSolarSystemObjectTable_metadata": PROVENANCE,
        "analyzeDiaSourceAssociationMetrics_config": PROVENANCE,
        "analyzeDiaSourceAssociationMetrics_log": PROVENANCE,
        "analyzeDiaSourceAssociationMetrics_metadata": PROVENANCE,
        "analyzeDiaSourceDetectionMetrics_config": PROVENANCE,
        "analyzeDiaSourceDetectionMetrics_log": PROVENANCE,
        "analyzeDiaSourceDetectionMetrics_metadata": PROVENANCE,
        "analyzeImageDifferenceMetrics_config": PROVENANCE,
        "analyzeImageDifferenceMetrics_log": PROVENANCE,
        "analyzeImageDifferenceMetrics_metadata": PROVENANCE,
        "analyzeLoadDiaCatalogsMetrics_config": PROVENANCE,
        "analyzeLoadDiaCatalogsMetrics_log": PROVENANCE,
        "analyzeLoadDiaCatalogsMetrics_metadata": PROVENANCE,
        "analyzePreliminarySummaryStats_config": PROVENANCE,
        "analyzePreliminarySummaryStats_log": PROVENANCE,
        "analyzePreliminarySummaryStats_metadata": PROVENANCE,
        "analyzeTrailedDiaSourceTable_config": PROVENANCE,
        "analyzeTrailedDiaSourceTable_log": PROVENANCE,
        "analyzeTrailedDiaSourceTable_metadata": PROVENANCE,
        "analyzeUnassociatedDirectSolarSystemObjectTable_config": PROVENANCE,
        "analyzeUnassociatedDirectSolarSystemObjectTable_log": PROVENANCE,
        "analyzeUnassociatedDirectSolarSystemObjectTable_metadata": PROVENANCE,
        "associateApdb_config": PROVENANCE,
        "associateApdb_log": PROVENANCE,
        "associateApdb_metadata": PROVENANCE,
        "associateSolarSystemDirectSource_config": PROVENANCE,
        "associateSolarSystemDirectSource_log": PROVENANCE,
        "associateSolarSystemDirectSource_metadata": PROVENANCE,
        "buildTemplate_config": PROVENANCE,
        "buildTemplate_log": PROVENANCE,
        "buildTemplate_metadata": PROVENANCE,
        "calibrateImage_config": PROVENANCE,
        "calibrateImage_log": PROVENANCE,
        "calibrateImage_metadata": PROVENANCE,
        "computeReliability_config": PROVENANCE,
        "computeReliability_log": PROVENANCE,
        "computeReliability_metadata": PROVENANCE,
        "detectAndMeasureDiaSource_config": PROVENANCE,
        "detectAndMeasureDiaSource_log": PROVENANCE,
        "detectAndMeasureDiaSource_metadata": PROVENANCE,
        "filterDiaSourcePostReliability_config": PROVENANCE,
        "filterDiaSourcePostReliability_log": PROVENANCE,
        "filterDiaSourcePostReliability_metadata": PROVENANCE,
        "filterDiaSource_config": PROVENANCE,
        "filterDiaSource_log": PROVENANCE,
        "filterDiaSource_metadata": PROVENANCE,
        "isr_config": PROVENANCE,
        "isr_log": PROVENANCE,
        "isr_metadata": PROVENANCE,
        "loadDiaCatalogs_config": PROVENANCE,
        "loadDiaCatalogs_log": PROVENANCE,
        "loadDiaCatalogs_metadata": PROVENANCE,
        "mpSkyEphemerisQuery_config": PROVENANCE,
        "mpSkyEphemerisQuery_log": PROVENANCE,
        "mpSkyEphemerisQuery_metadata": PROVENANCE,
        "packages": PROVENANCE,
        "singleFrameDetectAndMeasure_config": PROVENANCE,
        "singleFrameDetectAndMeasure_log": PROVENANCE,
        "singleFrameDetectAndMeasure_metadata": PROVENANCE,
        "standardizeDiaSource_config": PROVENANCE,
        "standardizeDiaSource_log": PROVENANCE,
        "standardizeDiaSource_metadata": PROVENANCE,
        "subtractImages_config": PROVENANCE,
        "subtractImages_log": PROVENANCE,
        "subtractImages_metadata": PROVENANCE,
    }
)
