import io
from itertools import cycle
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
    Hashable,
    cast,
)

import ipyleaflet  # type: ignore
import numpy as np
import pandas as pd
import plotly.express as px  # type: ignore
from numpydoc_decorator import doc  # type: ignore

from ..util import check_types
from . import base_params, map_params, plotly_params
from .base import AnophelesBase


class AnophelesSampleMetadata(AnophelesBase):
    def __init__(
        self,
        cohorts_analysis: Optional[str] = None,
        aim_analysis: Optional[str] = None,
        aim_metadata_dtype: Optional[Mapping[str, Any]] = None,
        taxon_colors: Optional[Mapping[str, str]] = None,
        **kwargs,
    ):
        # N.B., this class is designed to work cooperatively, and
        # so it's important that any remaining parameters are passed
        # to the superclass constructor.
        super().__init__(**kwargs)

        # If provided, this analysis version will override the
        # default value provided in the release configuration.
        self._cohorts_analysis_override = cohorts_analysis

        # If provided, this analysis version will override the
        # default value provided in the release configuration.
        self._aim_analysis_override = aim_analysis

        # N.B., the expected AIM metadata columns may vary between
        # data resources, and so column names and dtype need to be
        # passed in as parameters.
        self._aim_metadata_columns: Optional[List[str]] = None
        self._aim_metadata_dtype: Dict[str, Union[str, type, np.dtype]] = dict()
        if isinstance(aim_metadata_dtype, Mapping):
            self._aim_metadata_columns = list(aim_metadata_dtype.keys())
            self._aim_metadata_dtype.update(aim_metadata_dtype)
        self._aim_metadata_dtype["sample_id"] = "object"

        # Set up taxon colors.
        self._taxon_colors = taxon_colors

        # Set up extra metadata.
        self._extra_metadata: List = []

        # Initialize cache attributes.
        self._cache_sample_metadata: Dict = dict()

    def _metadata_paths(
        self,
        *,
        sample_sets: List[str],
        path_template: str,
        aim_analysis: Optional[str] = None,
        cohorts_analysis: Optional[str] = None,
    ) -> Dict[str, str]:
        paths = dict()
        for sample_set in sample_sets:
            release = self.lookup_release(sample_set=sample_set)
            release_path = self._release_to_path(release=release)
            if aim_analysis:
                path = path_template.format(
                    release_path=release_path,
                    sample_set=sample_set,
                    aim_analysis=aim_analysis,
                )
            elif cohorts_analysis:
                path = path_template.format(
                    release_path=release_path,
                    sample_set=sample_set,
                    cohorts_analysis=cohorts_analysis,
                )
            else:
                path = path_template.format(
                    release_path=release_path, sample_set=sample_set
                )
            paths[sample_set] = path
        return paths

    def _parse_metadata_paths(
        self,
        path_template: str,
        parse_metadata_func: Callable[[str, Union[bytes, Exception]], pd.DataFrame],
        sample_sets: Optional[base_params.sample_sets] = None,
        aim_analysis: Optional[str] = None,
        cohorts_analysis: Optional[str] = None,
    ) -> pd.DataFrame:
        # Normalise input parameters.
        sample_sets_prepped = self._prep_sample_sets_param(sample_sets=sample_sets)
        del sample_sets

        # Obtain paths for all files we need to fetch.
        file_paths: Mapping[str, str] = self._metadata_paths(
            sample_sets=sample_sets_prepped,
            path_template=path_template,
            aim_analysis=aim_analysis,
            cohorts_analysis=cohorts_analysis,
        )

        # Fetch all files. N.B., here is an optimisation, this allows us to fetch
        # multiple files concurrently.
        files: Mapping[str, Union[bytes, Exception]] = self.read_files(
            paths=file_paths.values(), on_error="return"
        )

        # Parse files into DataFrames.
        dfs = []
        for sample_set in sample_sets_prepped:
            path = file_paths[sample_set]
            data = files[path]
            df = parse_metadata_func(sample_set, data)
            dfs.append(df)

        # Concatenate all DataFrames.
        df_ret = pd.concat(dfs, axis=0, ignore_index=True)

        return df_ret

    def _parse_general_metadata(
        self, sample_set: str, data: Union[bytes, Exception]
    ) -> pd.DataFrame:
        if isinstance(data, bytes):
            dtype = {
                "sample_id": "object",
                "partner_sample_id": "object",
                "contributor": "object",
                "country": "object",
                "location": "object",
                "year": "int64",
                "month": "int64",
                "latitude": "float64",
                "longitude": "float64",
                "sex_call": "object",
            }
            # Mapping of string dtypes to actual dtypes
            dtype_map = {
                "object": str,
                "int64": np.int64,
                "float64": np.float64,
            }

            # Convert string dtypes to actual dtypes
            dtype_fixed: Mapping[Hashable, Union[str, np.dtype, type]] = {
                col: dtype_map.get(dtype[col], str) for col in dtype
            }

            df = pd.read_csv(io.BytesIO(data), dtype=dtype_fixed, na_values="")

            # Ensure all column names are lower case.
            df.columns = [c.lower() for c in df.columns]  # type: ignore

            # Add a couple of columns for convenience.
            df["sample_set"] = sample_set
            release = self.lookup_release(sample_set=sample_set)
            df["release"] = release

            # Derive a quarter column from month.
            df["quarter"] = df.apply(
                lambda row: ((row.month - 1) // 3) + 1 if row.month > 0 else -1,
                axis="columns",
            )

            # Add study columns.
            study_info = self.lookup_study_info(sample_set=sample_set)
            for column in study_info:
                df[column] = study_info[column]

            # Add terms-of-use columns.
            terms_of_use_info = self.lookup_terms_of_use_info(sample_set=sample_set)
            for column in terms_of_use_info:
                df[column] = terms_of_use_info[column]

            return df

        else:
            raise data

    @check_types
    @doc(
        summary="""
            Read general sample metadata for one or more sample sets into a pandas
            DataFrame.
        """,
        returns="A pandas DataFrame, one row per sample.",
    )
    def general_metadata(
        self, sample_sets: Optional[base_params.sample_sets] = None
    ) -> pd.DataFrame:
        return self._parse_metadata_paths(
            path_template="{release_path}/metadata/general/{sample_set}/samples.meta.csv",
            parse_metadata_func=self._parse_general_metadata,
            sample_sets=sample_sets,
        )

    @property
    def _sequence_qc_metadata_dtype(self):
        # Note: tests expect an ordered dictionary.
        # Note: insertion order in dictionary keys is guaranteed since Python 3.7
        # Note: using nullable dtypes (e.g. Int64 instead of int64) to allow missing data.

        dtype = {
            "sample_id": "object",
            "mean_cov": "Float64",
            "median_cov": "Int64",
            "modal_cov": "Int64",
        }

        for contig in sorted(self.config["CONTIGS"]):
            dtype[f"mean_cov_{contig}"] = "Float64"
            dtype[f"median_cov_{contig}"] = "Int64"
            dtype[f"mode_cov_{contig}"] = "Int64"

        dtype.update(
            {
                "frac_gen_cov": "Float64",
                "divergence": "Float64",
                "contam_pct": "Float64",
                "contam_LLR": "Float64",
            }
        )

        return dtype

    def _parse_sequence_qc_metadata(
        self, sample_set: str, data: Union[bytes, Exception]
    ) -> pd.DataFrame:
        if isinstance(data, bytes):
            # Get the dtype of the constant columns.
            dtype = self._sequence_qc_metadata_dtype

            # Read the CSV using the dtype dict.
            df = pd.read_csv(io.BytesIO(data), dtype=dtype, na_values="")

            return df

        elif isinstance(data, FileNotFoundError):
            # Sequence QC metadata are missing for this sample set,
            # so return a blank DataFrame.

            # Copy the sample ids from the general metadata.
            df_general = self.general_metadata(sample_sets=sample_set)
            df = df_general[["sample_id"]].copy()

            # Add the sequence QC columns with appropriate missing values.
            # For each column, set the value to either NA or NaN.
            for c, dtype in self._sequence_qc_metadata_dtype.items():
                if pd.api.types.is_integer_dtype(dtype):
                    # Note: this creates a column with dtype int64.
                    df[c] = -1
                else:
                    # Note: this creates a column with dtype float64.
                    df[c] = np.nan

            # Set the column data types.
            df = df.astype(self._sequence_qc_metadata_dtype)

            return df

        else:
            raise data

    @check_types
    @doc(
        summary="""
            Access sequence QC metadata for one or more sample sets.
        """,
        returns="""A pandas DataFrame, one row per sample. The columns are:
        `sample_id` is the identifier of the sample,
        `partner_sample_id` is the identifier of the sample used by the partners who contributed it,
        `contributor` is the partner who contributed the sample,
        `country` is the country the sample was collected in,
        `location` is the location the sample was collected in,
        `year` is the year the sample was collected,
        `month` is the month the sample was collected,
        `latitude` is the latitude of the location the sample was collected in,
        `longitude` is the longitude of the location the sample was collected in,
        `sex_call` is the sex of the sample,
        `sample_set` is the sample set containing the sample,
        `release` is the release containing the sample,
        `quarter` is the quarter of the year the sample was collected,
        `study_id* is the identifier of the study the sample set containing the sample came from,
        `study_url` is the URL of the study the sample set containing the sample came from,
        `terms_of_use_expiry_date` is the date the terms of use for the sample expire,
        `terms_of_use_url` is the URL of the terms of use for the sample,
        `unrestricted_use` indicates whether the sample can be used without restrictions (e.g., if the terms of use of expired),
        `mean_cov` is mean value of the coverage,
        `median_cov` is the median value of the coverage,
        `modal_cov` is the mode of the coverage,
        `mean_cov_2L` is mean value of the coverage on 2L,
        `median_cov_2L` is the median value of the coverage on 2L,
        `mode_cov_2L` is the mode of the coverage on 2L,
        `mean_cov_2R` is mean value of the coverage on 2R,
        `median_cov_2R` is the median value of the coverage on 2R,
        `mode_cov_2R` is the mode of the coverage on 2R,
        `mean_cov_3L` is mean value of the coverage on 3L,
        `median_cov_3L` is the median value of the coverage on 3L,
        `mode_cov_3L` is the mode of the coverage on 3L,
        `mean_cov_3R` is mean value of the coverage on 3R,
        `median_cov_3R` is the median value of the coverage on 3R,
        `mode_cov_3R` is the mode of the coverage on 3R,
        `mean_cov_X` is mean value of the coverage on X,
        `median_cov_X` is the median value of the coverage on X,
        `mode_cov_X` is the mode of the coverage on X,
        `frac_gen_cov` is the faction of the genome covered,
        `divergence` is the divergence,
        `contam_pct` is the percentage of contamination,
        `contam_LLR` is the log-likelihood ratio of contamination,
        `aim_species_fraction_arab` is the fraction of the gambcolu vs. arabiensis AIMs that indicated arabiensis (this column is only present for *Ag3*),
        `aim_species_fraction_colu` is the fraction of the gambiae vs. coluzzii AIMs that indicated coluzzii (this column is only present for *Ag3*),
        `aim_species_fraction_colu_no2l` is the fraction of the gambiae vs. coluzzii AIMs that indicated coluzzii, not including the chromosome arm 2L which contains an introgression (this column is only present for *Ag3*),
        `aim_species_gambcolu_arabiensis` is the taxonomic group assigned by the gambcolu vs. arabiensis AIMs (this column is only present for *Ag3*),
        `aim_species_gambiae_coluzzi` is the taxonomic group assigned by the gambiae vs. coluzzii AIMs (this column is only present for *Ag3*),
        `aim_species_gambcolu_arabiensis` is the taxonomic group assigned by the combination of both AIMs analyses (this column is only present for *Ag3*),
        `country_iso` is the ISO code of the country the sample was collected in,
        `admin1_name` is the name of the first administrative level the sample was collected in,
        `admin1_iso` is the ISO code of the first administrative level the sample was collected in,
        `admin2_name` is the name of the second administrative level the sample was collected in,
        `taxon` is the taxon assigned to the sample by the combination of the AIMs analysis and the cohort analysis,
        `cohort_admin1_year` is the cohort the sample belongs to when samples are grouped by first administrative level and year,
        `cohort_admin1_month` is the cohort the sample belongs to when samples are grouped by first administrative level and month,
        `cohort_admin1_quarter` is the cohort the sample belongs to when samples are grouped by first administrative level and quarter,
        `cohort_admin2_year` is the cohort the sample belongs to when samples are grouped by second administrative level and year,
        `cohort_admin2_month` is the cohort the sample belongs to when samples are grouped by second administrative level and month,
        `cohort_admin2_quarter` is the cohort the sample belong to when samples are grouped by second administrative level and quarter.
        """,
    )
    def sequence_qc_metadata(
        self, sample_sets: Optional[base_params.sample_sets] = None
    ) -> pd.DataFrame:
        return self._parse_metadata_paths(
            path_template="{release_path}/metadata/curation/{sample_set}/sequence_qc_stats.csv",
            parse_metadata_func=self._parse_sequence_qc_metadata,
            sample_sets=sample_sets,
        )

    @property
    def _cohorts_analysis(self):
        if self._cohorts_analysis_override:
            return self._cohorts_analysis_override
        else:
            # N.B., this will return None if the key is not present in the
            # config.
            return self.config.get("DEFAULT_COHORTS_ANALYSIS")

    @property
    def _cohorts_metadata_columns(self):
        # Handle changes to columns used in different analyses.
        cols = None
        if self._cohorts_analysis:
            if self._cohorts_analysis < "20230223":
                cols = (
                    "country_iso",
                    "admin1_name",
                    "admin1_iso",
                    "admin2_name",
                    "taxon",
                    "cohort_admin1_year",
                    "cohort_admin1_month",
                    "cohort_admin2_year",
                    "cohort_admin2_month",
                )
            # We assume that cohorts analyses from "20230223" onwards always include quarter
            # columns.
            else:
                cols = (
                    "country_iso",
                    "admin1_name",
                    "admin1_iso",
                    "admin2_name",
                    "taxon",
                    "cohort_admin1_year",
                    "cohort_admin1_month",
                    "cohort_admin1_quarter",
                    "cohort_admin2_year",
                    "cohort_admin2_month",
                    "cohort_admin2_quarter",
                )
        return cols

    @property
    def _cohorts_metadata_dtype(self):
        cols = self._cohorts_metadata_columns
        if cols:
            # All columns are string columns.
            dtype = {c: "object" for c in cols}
            dtype["sample_id"] = "object"
            return dtype

    def _parse_cohorts_metadata(
        self, sample_set: str, data: Union[bytes, Exception]
    ) -> pd.DataFrame:
        if isinstance(data, bytes):
            # Parse CSV data.
            dtype = self._cohorts_metadata_dtype
            df = pd.read_csv(io.BytesIO(data), dtype=dtype, na_values="")

            # Ensure all column names are lower case.
            df.columns = [c.lower() for c in df.columns]  # type: ignore

            # Rename some columns for consistent naming.
            df.rename(
                columns={
                    "adm1_iso": "admin1_iso",
                    "adm1_name": "admin1_name",
                    "adm2_name": "admin2_name",
                },
                inplace=True,
            )

            return df

        elif isinstance(data, FileNotFoundError):
            # Cohorts metadata are missing for this sample set, fill with a blank
            # DataFrame.
            df_general = self.general_metadata(sample_sets=sample_set)
            df = df_general[["sample_id"]].copy()
            for c in self._cohorts_metadata_columns:
                df[c] = np.nan
            df = df.astype(self._cohorts_metadata_dtype)
            return df

        else:
            raise data

    def _require_cohorts_analysis(self):
        if not self._cohorts_analysis:
            raise NotImplementedError(
                "Cohorts data not available for this data resource."
            )

    @check_types
    @doc(
        summary="""
            Access cohort membership metadata for one or more sample sets.
        """,
        returns="A pandas DataFrame, one row per sample.",
    )
    def cohorts_metadata(
        self, sample_sets: Optional[base_params.sample_sets] = None
    ) -> pd.DataFrame:
        self._require_cohorts_analysis()

        return self._parse_metadata_paths(
            path_template="{release_path}/metadata/cohorts_{cohorts_analysis}/{sample_set}/samples.cohorts.csv",
            parse_metadata_func=self._parse_cohorts_metadata,
            sample_sets=sample_sets,
            cohorts_analysis=self._cohorts_analysis,
        )

    @property
    def _aim_analysis(self):
        if self._aim_analysis_override:
            return self._aim_analysis_override
        else:
            # N.B., this will return None if the key is not present in the
            # config.
            return self.config.get("DEFAULT_AIM_ANALYSIS")

    def _parse_aim_metadata(
        self, sample_set: str, data: Union[bytes, Exception]
    ) -> pd.DataFrame:
        assert self._aim_metadata_columns is not None
        assert self._aim_metadata_dtype is not None
        if isinstance(data, bytes):
            # Parse CSV data.
            df = pd.read_csv(
                io.BytesIO(data),
                dtype=cast(
                    Mapping[Hashable, Union[str, type, np.dtype]],
                    self._aim_metadata_dtype,
                ),
                na_values="",
            )

            # Ensure all column names are lower case.
            df.columns = [c.lower() for c in df.columns]  # type: ignore

            return df

        elif isinstance(data, FileNotFoundError):
            # AIM data are missing for this sample set, fill with a blank DataFrame.
            df_general = self.general_metadata(sample_sets=sample_set)
            df = df_general[["sample_id"]].copy()
            for c in self._aim_metadata_columns:
                df[c] = np.nan
            df = df.astype(self._aim_metadata_dtype)
            return df

        else:
            raise data

    def _require_aim_analysis(self):
        if not self._aim_analysis:
            raise NotImplementedError("AIM data not available for this data resource.")

    @check_types
    @doc(
        summary="""
            Access ancestry-informative marker (AIM) metadata for one or more
            sample sets.
        """,
        returns="A pandas DataFrame, one row per sample.",
    )
    def aim_metadata(
        self, sample_sets: Optional[base_params.sample_sets] = None
    ) -> pd.DataFrame:
        self._require_aim_analysis()

        return self._parse_metadata_paths(
            path_template="{release_path}/metadata/species_calls_aim_{aim_analysis}/{sample_set}/samples.species_aim.csv",
            parse_metadata_func=self._parse_aim_metadata,
            sample_sets=sample_sets,
            aim_analysis=self._aim_analysis,
        )

    @check_types
    @doc(
        summary="""
            Add extra sample metadata, e.g., including additional columns
            which you would like to use to query and group samples.
        """,
        parameters=dict(
            data="""
                A data frame with one row per sample. Must include either a
                "sample_id" or "partner_sample_id" column.
            """,
            on="""
                Name of column to use when merging with sample metadata.
            """,
        ),
        notes="""
            The values in the column containing sample identifiers must be
            unique.
        """,
    )
    def add_extra_metadata(self, data: pd.DataFrame, on: str = "sample_id"):
        # Check parameters.
        if not isinstance(data, pd.DataFrame):
            raise TypeError("`data` parameter must be a pandas DataFrame")
        if on not in data.columns:
            raise ValueError(f"dataframe does not contain column {on!r}")
        if on not in {"sample_id", "partner_sample_id"}:
            raise ValueError(
                "`on` parameter must be either 'sample_id' or 'partner_sample_id'"
            )

        # Check for uniqueness.
        if not data[on].is_unique:
            raise ValueError(f"column {on!r} does not have unique values")

        # check there are matching samples.
        df_samples = self.sample_metadata()
        loc_isec = data[on].isin(df_samples[on])
        if not loc_isec.any():
            raise ValueError("no matching samples found")

        # store extra metadata
        self._extra_metadata.append((on, data.copy()))

    @doc(
        summary="Clear any extra metadata previously added",
    )
    def clear_extra_metadata(self):
        self._extra_metadata = []

    @check_types
    @doc(
        summary="Access sample metadata for one or more sample sets.",
        returns="A dataframe of sample metadata, one row per sample.",
    )
    def sample_metadata(
        self,
        sample_sets: Optional[base_params.sample_sets] = None,
        sample_query: Optional[base_params.sample_query] = None,
        sample_query_options: Optional[base_params.sample_query_options] = None,
        sample_indices: Optional[base_params.sample_indices] = None,
    ) -> pd.DataFrame:
        # Extra parameter checks.
        base_params.validate_sample_selection_params(
            sample_query=sample_query, sample_indices=sample_indices
        )

        # Normalise parameters.
        prepped_sample_sets = self._prep_sample_sets_param(sample_sets=sample_sets)
        del sample_sets
        cache_key = tuple(prepped_sample_sets)

        try:
            # Attempt to retrieve from the cache.
            df_samples = self._cache_sample_metadata[cache_key]

        except KeyError:
            with self._spinner(desc="Load sample metadata"):
                ## Build a single DataFrame using all available metadata.

                # Get the general sample metadata.
                # Note: this includes study and terms-of-use info.
                df_samples = self.general_metadata(sample_sets=prepped_sample_sets)

                # Merge with the sequence QC metadata.
                df_sequence_qc = self.sequence_qc_metadata(
                    sample_sets=prepped_sample_sets
                )

                # Note: merging can change column dtypes
                df_samples = df_samples.merge(
                    df_sequence_qc, on="sample_id", sort=False, how="left"
                )

                # If available, merge with the AIM metadata.
                if self._aim_analysis:
                    df_aim = self.aim_metadata(sample_sets=prepped_sample_sets)
                    df_samples = df_samples.merge(
                        df_aim, on="sample_id", sort=False, how="left"
                    )

                # If available, merge with the cohorts metadata.
                if self._cohorts_analysis:
                    df_cohorts = self.cohorts_metadata(sample_sets=prepped_sample_sets)
                    df_samples = df_samples.merge(
                        df_cohorts, on="sample_id", sort=False, how="left"
                    )

            # Store sample metadata in the cache.
            self._cache_sample_metadata[cache_key] = df_samples

        # Add extra metadata.
        for on, data in self._extra_metadata:
            df_samples = df_samples.merge(data, how="left", on=on)

        # For convenience, apply a sample selection.
        if sample_query is not None:
            # Assume a pandas query string.
            sample_query_options = sample_query_options or {}
            df_samples = df_samples.query(sample_query, **sample_query_options)
            df_samples = df_samples.reset_index(drop=True)
        elif sample_indices is not None:
            # Assume it is an indexer.
            df_samples = df_samples.iloc[sample_indices]
            df_samples = df_samples.reset_index(drop=True)

        return df_samples.copy()

    @check_types
    @doc(
        summary="""
            Create a pivot table showing numbers of samples available by space,
            time and taxon.
        """,
        parameters=dict(
            index="Sample metadata columns to use for the pivot table index.",
            columns="Sample metadata columns to use for the pivot table columns.",
        ),
        returns="Pivot table of sample counts. One row per admin2_year cohort. Unless otherwise specified using the `columns` parameters, the samples are grouped according to their taxon and then counted.",
    )
    def count_samples(
        self,
        sample_sets: Optional[base_params.sample_sets] = None,
        sample_query: Optional[base_params.sample_query] = None,
        sample_query_options: Optional[base_params.sample_query_options] = None,
        index: Union[str, Sequence[str]] = (
            "country",
            "admin1_iso",
            "admin1_name",
            "admin2_name",
            "year",
        ),
        columns: Union[str, Sequence[str]] = "taxon",
    ) -> pd.DataFrame:
        # Load sample metadata.
        df_samples = self.sample_metadata(
            sample_sets=sample_sets,
            sample_query=sample_query,
            sample_query_options=sample_query_options,
        )

        # Create pivot table.
        df_pivot = df_samples.pivot_table(
            index=index,
            columns=columns,
            values="sample_id",
            aggfunc="count",
            fill_value=0,
        )

        return df_pivot

    @check_types
    @doc(
        summary="""
            Plot an interactive map showing sampling locations using ipyleaflet.
        """,
        parameters=dict(
            min_samples="""
                Minimum number of samples required to show a marker for a given
                location.
            """,
            count_by="""
                Metadata column to report counts of samples by for each location.
            """,
        ),
        returns="Ipyleaflet map widget.",
    )
    def plot_samples_interactive_map(
        self,
        sample_sets: Optional[base_params.sample_sets] = None,
        sample_query: Optional[base_params.sample_query] = None,
        sample_query_options: Optional[base_params.sample_query_options] = None,
        basemap: Optional[map_params.basemap] = map_params.basemap_default,
        center: map_params.center = map_params.center_default,
        zoom: map_params.zoom = map_params.zoom_default,
        height: map_params.height = map_params.height_default,
        width: map_params.width = map_params.width_default,
        min_samples: int = 1,
        count_by: str = "taxon",
    ) -> ipyleaflet.Map:
        # Normalise height and width to string
        if isinstance(height, int):
            height = f"{height}px"
        if isinstance(width, int):
            width = f"{width}px"

        # Load sample metadata.
        df_samples = self.sample_metadata(
            sample_sets=sample_sets,
            sample_query=sample_query,
            sample_query_options=sample_query_options,
        )

        # Pivot taxa by locations.
        location_composite_key = [
            "country",
            "admin1_iso",
            "admin1_name",
            "admin2_name",
            "location",
            "latitude",
            "longitude",
        ]
        df_pivot = df_samples.pivot_table(
            index=location_composite_key,
            columns=count_by,
            values="sample_id",
            aggfunc="count",
            fill_value=0,
        )

        # Append aggregations to pivot.
        df_location_aggs = df_samples.groupby(location_composite_key).agg(
            {
                "year": lambda x: ", ".join(str(y) for y in sorted(x.unique())),
                "sample_set": lambda x: ", ".join(str(y) for y in sorted(x.unique())),
                "contributor": lambda x: ", ".join(str(y) for y in sorted(x.unique())),
            }
        )
        df_pivot = df_pivot.merge(
            df_location_aggs, on=location_composite_key, validate="one_to_one"
        )

        # Handle basemap.
        basemap_abbrevs = map_params.basemap_abbrevs

        # Determine basemap_provider via basemap
        if isinstance(basemap, str):
            # Interpret string
            # Support case-insensitive basemap abbreviations
            basemap_str = basemap.lower()
            if basemap_str not in basemap_abbrevs:
                raise ValueError(
                    f"Basemap abbreviation not recognised: {basemap_str!r}; try one of {list(basemap_abbrevs.keys())}"
                )
            basemap_provider = basemap_abbrevs[basemap_str]
        elif basemap is None:
            # Default.
            basemap_provider = ipyleaflet.basemaps.Esri.WorldImagery
        else:
            # Expect dict or TileProvider or TileLayer.
            basemap_provider = basemap

        # Create a map.
        samples_map = ipyleaflet.Map(
            center=center,
            zoom=zoom,
            basemap=basemap_provider,
        )
        scale_control = ipyleaflet.ScaleControl(position="bottomleft")
        samples_map.add(scale_control)
        samples_map.layout.height = height
        samples_map.layout.width = width

        # Add markers.
        count_factors = df_samples[count_by].dropna().sort_values().unique()
        for _, row in df_pivot.reset_index().iterrows():
            title = (
                f"Location: {row.location} ({row.latitude:.3f}, {row.longitude:.3f})"
            )
            title += f"\nAdmin level 2: {row.admin2_name}"
            title += f"\nAdmin level 1: {row.admin1_name} ({row.admin1_iso})"
            title += f"\nCountry: {row.country}"
            title += f"\nYears: {row.year}"
            title += f"\nSample sets: {row.sample_set}"
            title += f"\nContributors: {row.contributor}"
            title += "\nNo. specimens: "
            all_n = 0
            for factor in count_factors:
                # Get the number of samples in this taxon
                n = row[factor]
                # Count the number of samples in all taxa
                all_n += n
                if n > 0:
                    title += f"{n} {factor}; "
            # Only show a marker when there are enough samples
            if all_n >= min_samples:
                marker = ipyleaflet.Marker(
                    location=(row.latitude, row.longitude),
                    draggable=False,
                    title=title,
                )
                samples_map.add(marker)

        return samples_map

    @check_types
    @doc(
        summary="""
            Load a data catalog providing URLs for downloading BAM, VCF and Zarr
            files for samples in a given sample set.
        """,
        returns="""One row per sample, the columns are
        `sample_id`, the identifier of the sample,
        `alignments_bam`, the URL of the alignments BAM file,
        `snp_genotypes_vcf`, the URL of the SNP genotypes VCF file,
        `snp_genotypes_zarr`, the URL of the SNP genotypes Zarr file.""",
    )
    def wgs_data_catalog(self, sample_set: base_params.sample_set):
        # Look up release for sample set.
        release = self.lookup_release(sample_set=sample_set)
        release_path = self._release_to_path(release=release)

        # Load data catalog.
        path = f"{self._base_path}/{release_path}/metadata/general/{sample_set}/wgs_snp_data.csv"
        with self._fs.open(path) as f:
            df = pd.read_csv(f, na_values="")

        # Normalise columns.
        df = df[
            [
                "sample_id",
                "alignments_bam",
                "snp_genotypes_vcf",
                "snp_genotypes_zarr",
            ]
        ]

        return df

    @check_types
    @doc(
        summary="""
            Load a data accessions catalog providing ENA run accessions
            for samples in a given sample set.
        """,
        returns="One row per sample, columns provide run accessions.",
    )
    def wgs_run_accessions(self, sample_set: base_params.sample_set):
        # Look up release for sample set.
        release = self.lookup_release(sample_set=sample_set)
        release_path = self._release_to_path(release=release)

        # Load data catalog.
        path = f"{self._base_path}/{release_path}/metadata/general/{sample_set}/wgs_accession_data.csv"
        with self._fs.open(path) as f:
            df = pd.read_csv(f, na_values="")

        # Normalise columns.
        df = df[
            [
                "sample_id",
                "run_ena",
            ]
        ]

        return df

    def _prep_sample_selection_cache_params(
        self,
        *,
        sample_sets: Optional[base_params.sample_sets],
        sample_query: Optional[base_params.sample_query],
        sample_query_options: Optional[base_params.sample_query_options],
        sample_indices: Optional[base_params.sample_indices],
    ) -> Tuple[List[str], Optional[List[int]]]:
        # Normalise sample sets.
        sample_sets = self._prep_sample_sets_param(sample_sets=sample_sets)

        if sample_query is not None:
            # Resolve query to a list of integers for more cache hits - we
            # do this because there are different ways to write the same pandas
            # query, and so it's better to evaluate the query and use a list of
            # integer indices instead.
            df_samples = self.sample_metadata(sample_sets=sample_sets)
            sample_query_options = sample_query_options or {}
            loc_samples = df_samples.eval(sample_query, **sample_query_options).values
            sample_indices = np.nonzero(loc_samples)[0].tolist()

        return sample_sets, sample_indices

    def _results_cache_add_analysis_params(self, params: dict):
        super()._results_cache_add_analysis_params(params)
        params["cohorts_analysis"] = self._cohorts_analysis
        params["aim_analysis"] = self._aim_analysis

    @check_types
    @doc(
        summary="Get the metadata for a specific sample and sample set.",
        returns="The metadata for the specified sample.",
    )
    def lookup_sample(
        self,
        sample: base_params.sample,
        sample_set: Optional[base_params.sample_set] = None,
    ) -> pd.core.series.Series:
        df_samples = self.sample_metadata(sample_sets=sample_set).set_index("sample_id")
        sample_rec = None
        if isinstance(sample, str):
            sample_rec = df_samples.loc[sample]
        else:
            assert isinstance(sample, int)
            sample_rec = df_samples.iloc[sample]
        return sample_rec

    @check_types
    @doc(
        summary="""
            Plot a bar chart showing the number of samples available, grouped by
            some variable such as country or year.
        """,
        parameters=dict(
            x="Name of sample metadata column to plot on the X axis.",
            color="Name of the sample metadata column to color bars by.",
            sort="If True, sort the bars in size order.",
            kwargs="Passed through to px.bar().",
        ),
    )
    def plot_samples_bar(
        self,
        x: str,
        color: Optional[str] = None,
        sort: bool = True,
        sample_sets: Optional[base_params.sample_sets] = None,
        sample_query: Optional[base_params.sample_query] = None,
        sample_query_options: Optional[base_params.sample_query_options] = None,
        template: plotly_params.template = "plotly_white",
        width: plotly_params.fig_width = 800,
        height: plotly_params.fig_height = 600,
        show: plotly_params.show = True,
        renderer: plotly_params.renderer = None,
        **kwargs,
    ) -> plotly_params.figure:
        # Load sample metadata.
        df_samples = self.sample_metadata(
            sample_sets=sample_sets,
            sample_query=sample_query,
            sample_query_options=sample_query_options,
        )

        # Special handling for plotting by year.
        if x == "year":
            # Remove samples with missing year.
            df_samples = df_samples.query("year > 0")

        # Construct a long-form dataframe to plot.
        if color:
            grouper: Union[str, List[str]] = [x, color]
        else:
            grouper = x
        df_plot = df_samples.groupby(grouper).agg({"sample_id": "count"}).reset_index()

        # Deal with request to sort by bar size.
        if sort:
            df_sort = (
                df_samples.groupby(x)
                .agg({"sample_id": "count"})
                .reset_index()
                .sort_values("sample_id")
            )
            x_order = df_sort[x].values
            category_orders = kwargs.get("category_orders", dict())
            category_orders.setdefault(x, x_order)
            kwargs["category_orders"] = category_orders

        # Make the plot.
        fig = px.bar(
            df_plot,
            x=x,
            y="sample_id",
            color=color,
            template=template,
            width=width,
            height=height,
            **kwargs,
        )

        # Visual styling.
        fig.update_layout(
            xaxis_title=x.capitalize(),
            yaxis_title="No. samples",
        )
        if color:
            fig.update_layout(legend_title=color.capitalize())

        if show:  # pragma: no cover
            fig.show(renderer=renderer)
            return None
        else:
            return fig

    def _setup_sample_symbol(
        self,
        *,
        data,
        symbol,
    ):
        if symbol is None:
            return None

        # Handle the symbol parameter.
        if isinstance(symbol, str):
            if "cohort_" + symbol in data.columns:
                # Convenience to allow things like "admin1_year" instead of "cohort_admin1_year".
                symbol_prepped = "cohort_" + symbol
            else:
                symbol_prepped = symbol
            if symbol_prepped not in data.columns:
                raise ValueError(
                    f"{symbol_prepped!r} is not a known column in the data."
                )

        else:
            # Custom grouping using queries.
            assert isinstance(symbol, Mapping)
            data["symbol"] = ""
            for key, value in symbol.items():
                data.loc[data.query(value).index, "symbol"] = key
            symbol_prepped = "symbol"

        # Handle missing data in a consistent way.
        data[symbol_prepped] = data[symbol_prepped].fillna("<NA>")

        return symbol_prepped

    def _setup_sample_colors_plotly(
        self,
        *,
        data,
        color,
        color_discrete_sequence,
        color_discrete_map,
        category_orders,
    ):
        # Check for no color.
        if color is None:
            # Bail out early.
            return None, None, None

        # Special handling for taxon colors.
        if color == "taxon" and color_discrete_map is None:
            # Special case, default taxon colors and order.
            color_discrete_map = self._taxon_colors

        if isinstance(color, str):
            if "cohort_" + color in data.columns:
                # Convenience to allow things like "admin1_year" instead of "cohort_admin1_year".
                color_prepped = "cohort_" + color
            else:
                color_prepped = color

            if color_prepped not in data.columns:
                raise ValueError(
                    f"{color_prepped!r} is not a known column in the data."
                )

        else:
            # Custom grouping using queries.
            assert isinstance(color, Mapping)
            data["color"] = ""
            for key, value in color.items():
                data.loc[data.query(value).index, "color"] = key
            color_prepped = "color"

        # Finish handling of color parameter.
        del color

        # Handle missing data in a consistent way.
        data[color_prepped] = data[color_prepped].fillna("<NA>")

        # Obtain the values that we will be mapping to colors.
        color_data_unique_values = data[color_prepped].unique()

        # Now set up color choices.
        if color_discrete_map is None:
            # Choose a color palette.
            if color_discrete_sequence is None:
                if len(color_data_unique_values) <= 10:
                    color_discrete_sequence = px.colors.qualitative.Plotly
                else:
                    color_discrete_sequence = px.colors.qualitative.Alphabet

            # Map values to colors.
            color_discrete_map_prepped = {
                v: c
                for v, c in zip(
                    color_data_unique_values, cycle(color_discrete_sequence)
                )
            }

        else:
            color_discrete_map_prepped = color_discrete_map

        # Consistent color for missing data.
        color_discrete_map_prepped["<NA>"] = "black"

        # Finished handling of color map params.
        del color_discrete_map
        del color_discrete_sequence

        # Define category orders.
        if category_orders is None:
            # Default ordering.
            category_orders_prepped = {color_prepped: color_data_unique_values.tolist()}

        else:
            category_orders_prepped = category_orders

        # Finised handling of category orders.
        del category_orders

        return (
            color_prepped,
            color_discrete_map_prepped,
            category_orders_prepped,
        )

    def _setup_sample_hover_data_plotly(
        self,
        *,
        color,
        symbol,
    ):
        hover_data = [
            "sample_id",
            "partner_sample_id",
            "sample_set",
            "taxon",
            "country",
            "admin1_iso",
            "admin1_name",
            "admin2_name",
            "location",
            "year",
            "month",
        ]
        if color and color not in hover_data:
            hover_data.append(color)
        if symbol and symbol not in hover_data:
            hover_data.append(symbol)
        return hover_data

    def _setup_cohort_queries(
        self,
        cohorts: base_params.cohorts,
        sample_sets: Optional[base_params.sample_sets],
        sample_query: Optional[base_params.sample_query],
        sample_query_options: Optional[base_params.sample_query_options],
        cohort_size: Optional[base_params.cohort_size],
        min_cohort_size: Optional[base_params.min_cohort_size],
    ):
        """Convenience function to normalise the `cohorts` paramater to a
        dictionary mapping cohort labels to sample metadata queries."""

        if isinstance(cohorts, dict):
            # User has supplied a custom dictionary mapping cohort identifiers
            # to pandas queries.
            cohort_queries = cohorts

        else:
            assert isinstance(cohorts, str)
            # User has supplied a column in the sample metadata.
            df_samples = self.sample_metadata(
                sample_sets=sample_sets,
                sample_query=sample_query,
                sample_query_options=sample_query_options,
            )

            # Determine column in dataframe - allow abbreviation.
            if "cohort_" + cohorts in df_samples.columns:
                cohorts = "cohort_" + cohorts
            if cohorts not in df_samples.columns:
                raise ValueError(
                    f"{cohorts!r} is not a known column in the sample metadata"
                )

            # Find cohort labels and build queries dictionary.
            cohort_labels = sorted(df_samples[cohorts].dropna().unique())
            cohort_queries = {coh: f"{cohorts} == '{coh}'" for coh in cohort_labels}

        # Handle sample_query parameter.
        if sample_query is not None:
            cohort_queries = {
                cohort_label: f"({cohort_query}) and ({sample_query})"
                for cohort_label, cohort_query in cohort_queries.items()
            }

        # Check cohort sizes, drop any cohorts which are too small.
        cohort_queries_checked = dict()
        for cohort_label, cohort_query in cohort_queries.items():
            df_cohort_samples = self.sample_metadata(
                sample_sets=sample_sets, sample_query=cohort_query
            )
            n_samples = len(df_cohort_samples)
            if min_cohort_size is not None:
                cohort_size = min_cohort_size
            if cohort_size is not None and n_samples < cohort_size:
                print(
                    f"Cohort ({cohort_label}) has insufficient samples ({n_samples}) for requested cohort size ({cohort_size}), dropping."
                )
            else:
                cohort_queries_checked[cohort_label] = cohort_query

        return cohort_queries_checked

    @check_types
    @doc(
        summary="""
            Read data for a specific cohort set, including cohort size,
            country code, taxon, administrative units name, ISO code, geoBoundaries
            shape ID and representative latitude and longitude points.
        """,
        parameters=dict(
            cohort_set="""
                A cohort set name. Accepted values are:
                "admin1_month", "admin1_quarter", "admin1_year",
                "admin2_month", "admin2_quarter", "admin2_year".
            """
        ),
        returns="""A dataframe of cohort data, one row per cohort. There are up to 18 columns:
        `cohort_id` is the identifier of the cohort,
        `cohort_size` is the number of samples in the cohort,
        `country` is the country the cohort is from,
        `country_alpha2` is the ISO alpha-2 code for the country the cohort is from,
        `country_alpha3` is the ISO alpha-3 code for the country the cohort is from,
        `taxon` is the taxon of the samples in the cohort,
        `year` is the year the samples in the cohort were collected in,
        `quarter` is the quarter the samples in the cohort were collected in (this column is only present if the temporal dimension is *quarter* or *month*),
        `month` is the month the samples in the cohort were collected in (this column is only present if the temporal dimension is *month*),
        `admin1_name` is the name of the first administrative level the samples in the cohort were collected in,
        `admin1_iso` is the ISO code of the first administrative level the samples in the cohort were collected in,
        `admin1_geoboundaries_shape_id` is the identifier of the geoboundary shape corresponding to the first administrative level the samples in the cohort were collected in,
        `admin1_representative_longitude` is the representative longitude for the first administrative level the samples in the cohort were collected in,
        `admin1_representative_latitude` is the representative latitude for the first administrative level the samples in the cohort were collected in,
        `admin2_name` is the name of the second administrative level the samples in the cohort were collected in (this column is only present if the spatial dimension is *admin2*),
        `admin2_iso` is the ISO code of the second administrative level the samples in the cohort were collected in (this column is only present if the spatial dimension is *admin2*),
        `admin2_geoboundaries_shape_id` is the identifier of the geoboundary shape corresponding to the second administrative level the samples in the cohort were collected in (this column is only present if the spatial dimension is *admin2*),
        `admin2_representative_longitude` is the representative longitude for the second administrative level the samples in the cohort were collected in (this column is only present if the spatial dimension is *admin2*),
        `admin2_representative_latitude` is the representative latitude for the second administrative level the samples in the cohort were collected in (this column is only present if the spatial dimension is *admin2*).
        """,
    )
    def cohorts(
        self,
        cohort_set: base_params.cohorts,
    ) -> pd.DataFrame:
        major_version_path = self._major_version_path
        cohorts_analysis = self._cohorts_analysis

        path = f"{major_version_path[:2]}_cohorts/cohorts_{cohorts_analysis}/cohorts_{cohort_set}.csv"

        # Read the manifest into a pandas dataframe.
        with self.open_file(path) as f:
            df_cohorts = pd.read_csv(f, sep=",", na_values="")

        # Ensure all column names are lower case.
        df_cohorts.columns = [c.lower() for c in df_cohorts.columns]  # type: ignore

        return df_cohorts

    @check_types
    @doc(
        summary="""
            Plot markers on a map showing sample locations
            as a Mapbox scatter plot.
        """,
        parameters=dict(
            kwargs="Passed through to px.scatter_mapbox().",
        ),
    )
    def plot_sample_location_mapbox(
        self,
        *,
        sample_sets: Optional[base_params.sample_sets],
        sample_query: Optional[base_params.sample_query] = None,
        sample_query_options: Optional[base_params.sample_query_options] = None,
        marker_size: plotly_params.marker_size = 10,
        color: plotly_params.color = "admin1_name",
        color_discrete_sequence: plotly_params.color_discrete_sequence = px.colors.qualitative.Prism,
        category_orders: plotly_params.category_order = None,
        hover_name: plotly_params.hover_name = "location",
        zoom: plotly_params.zoom = None,
        width: plotly_params.fig_width = 800,
        height: plotly_params.fig_height = 600,
        show: plotly_params.show = True,
        renderer: plotly_params.renderer = None,
        **kwargs,
    ) -> plotly_params.figure:
        # Get the sample metadata.
        df_samples = self.sample_metadata(
            sample_sets=sample_sets,
            sample_query=sample_query,
            sample_query_options=sample_query_options,
        )

        # Set the location columns to use from the sample metadata.
        location_columns = [
            "country",
            "admin1_iso",
            "admin1_name",
            "admin2_name",
            "location",
            "latitude",
            "longitude",
        ]

        # Trim and dedupe the sample locations.
        # Sort by `color` column by default, which can be overridden via category_orders.
        df_locations = df_samples[location_columns].drop_duplicates().sort_values(color)

        fig = px.scatter_mapbox(
            df_locations,
            lat="latitude",
            lon="longitude",
            mapbox_style="open-street-map",
            zoom=zoom,
            color=color,
            category_orders=category_orders,
            color_discrete_sequence=color_discrete_sequence,
            hover_name=hover_name,
            hover_data=location_columns,
            width=width,
            height=height,
            **kwargs,
        )

        # Set the size of the markers.
        fig.update_traces(marker=dict(size=marker_size))

        if show:  # pragma: no cover
            fig.show(renderer=renderer)
            return None
        else:
            return fig

    @check_types
    @doc(
        summary="""
            Plot markers on a map showing sample locations
            as a geographic scatter plot.
        """,
        parameters=dict(
            kwargs="Passed through to px.scatter_mapbox().",
        ),
    )
    def plot_sample_location_geo(
        self,
        *,
        sample_sets: Optional[base_params.sample_sets],
        sample_query: Optional[base_params.sample_query] = None,
        sample_query_options: Optional[base_params.sample_query_options] = None,
        marker_size: plotly_params.marker_size = 10,
        color: plotly_params.color = "admin1_name",
        color_discrete_sequence: plotly_params.color_discrete_sequence = px.colors.qualitative.Prism,
        category_orders: plotly_params.category_order = None,
        hover_name: plotly_params.hover_name = "location",
        fitbounds: plotly_params.fitbounds = "locations",
        scope: plotly_params.scope = "world",
        width: plotly_params.fig_width = 800,
        height: plotly_params.fig_height = 600,
        show: plotly_params.show = True,
        renderer: plotly_params.renderer = None,
        **kwargs,
    ) -> plotly_params.figure:
        # Get the sample metadata.
        df_samples = self.sample_metadata(
            sample_sets=sample_sets,
            sample_query=sample_query,
            sample_query_options=sample_query_options,
        )

        # Set the location columns to use from the sample metadata.
        location_columns = [
            "country",
            "admin1_iso",
            "admin1_name",
            "admin2_name",
            "location",
            "latitude",
            "longitude",
        ]

        # Trim and dedupe the sample locations.
        # Sort by `color` column by default, which can be overridden via category_orders.
        df_locations = df_samples[location_columns].drop_duplicates().sort_values(color)

        fig = px.scatter_geo(
            df_locations,
            lat="latitude",
            lon="longitude",
            scope=scope,
            height=height,
            width=width,
            color=color,
            hover_name=hover_name,
            hover_data=location_columns,
            category_orders=category_orders,
            color_discrete_sequence=color_discrete_sequence,
            fitbounds=fitbounds,
            **kwargs,
        )

        # Set the size of the markers.
        fig.update_traces(marker=dict(size=marker_size))

        if show:  # pragma: no cover
            fig.show(renderer=renderer)
            return None
        else:
            return fig


def locate_cohorts(*, cohorts, data, min_cohort_size):
    # Build cohort dictionary where key=cohort_id, value=loc_coh.
    coh_dict = {}

    if isinstance(cohorts, Mapping):
        # User has supplied a custom dictionary mapping cohort identifiers
        # to pandas queries.

        for coh, query in cohorts.items():
            loc_coh = data.eval(query).values
            coh_dict[coh] = loc_coh

    else:
        assert isinstance(cohorts, str)
        # User has supplied the name of a sample metadata column.

        # Convenience to allow things like "admin1_year" instead of "cohort_admin1_year".
        if "cohort_" + cohorts in data.columns:
            cohorts = "cohort_" + cohorts

        # Check the given cohort set exists.
        if cohorts not in data.columns:
            raise ValueError(f"{cohorts!r} is not a known column in the data.")
        cohort_labels = data[cohorts].dropna().unique()

        # Remove the nans and sort.
        cohort_labels = sorted([c for c in cohort_labels if isinstance(c, str)])
        for coh in cohort_labels:
            loc_coh = data[cohorts] == coh
            coh_dict[coh] = loc_coh.values

    # Remove cohorts below minimum cohort size.
    coh_dict = {
        coh: loc_coh
        for coh, loc_coh in coh_dict.items()
        if np.count_nonzero(loc_coh) >= min_cohort_size
    }

    # Early check for no cohorts.
    if len(coh_dict) == 0:
        raise ValueError(
            "No cohorts available for the given sample selection parameters and minimum cohort size."
        )

    return coh_dict
