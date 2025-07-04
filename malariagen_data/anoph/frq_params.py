"""Parameter definitions for functions computing and plotting allele frequencies."""

from typing import Literal, List, Optional, Tuple, Union

import xarray as xr
from typing_extensions import Annotated, TypeAlias

drop_invariant: TypeAlias = Annotated[
    bool,
    """
    If True, drop variants not observed in the selected samples.
    """,
]

effects: TypeAlias = Annotated[bool, "If True, add SNP effect annotations."]

area_by: TypeAlias = Annotated[
    str,
    """
    Column name in the sample metadata to use to group samples spatially. E.g.,
    use "admin1_iso" or "admin1_name" to group by level 1 administrative
    divisions, or use "admin2_name" to group by level 2 administrative
    divisions.
    """,
]

period_by: TypeAlias = Annotated[
    Union[str, Literal["year", "quarter", "month"]],
    "Either the length of time to group samples temporally or the name the column to use.",
]

variant_query: TypeAlias = Annotated[
    str,
    "A pandas query to be evaluated against variants.",
]

nobs_mode: TypeAlias = Annotated[
    Literal["called", "fixed"],
    """
    Method for calculating the denominator when computing frequencies. If
    "called" then use the number of called alleles, i.e., number of samples
    with non-missing genotype calls multiplied by 2. If "fixed" then use the
    number of samples multiplied by 2.
    """,
]

nobs_mode_default: nobs_mode = "called"

ci_method: TypeAlias = Annotated[
    Literal["normal", "agresti_coull", "beta", "wilson", "binom_test"],
    """
    Method to use for computing confidence intervals, passed through to
    `statsmodels.stats.proportion.proportion_confint`.
    """,
]

ci_method_default: ci_method = "wilson"

ds_frequencies_advanced: TypeAlias = Annotated[
    xr.Dataset,
    """
    A dataset of variant frequencies, such as returned by
    `snp_allele_frequencies_advanced()`,
    `aa_allele_frequencies_advanced()` or
    `gene_cnv_frequencies_advanced()`.
    """,
]

include_counts: TypeAlias = Annotated[
    bool,
    "Include columns with allele counts and number of non-missing allele calls (nobs).",
]

taxa: TypeAlias = Annotated[
    Optional[Union[str, List[str], Tuple[str, ...]]],
    "The taxon or taxa to restrict the dataset to.",
]

areas: TypeAlias = Annotated[
    Optional[Union[str, List[str], Tuple[str, ...]]],
    "The area or areas to restrict the dataset to.",
]

taxon_by: TypeAlias = Annotated[
    str,
    "The column to use for taxon stratification.",
]

taxon_by_default: taxon_by = "taxon"
