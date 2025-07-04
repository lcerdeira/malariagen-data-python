import pytest
import plotly.graph_objects as go  # type: ignore

import numpy as np
import pandas as pd
import random


def check_plot_frequencies_heatmap(api, frq_df):
    fig = api.plot_frequencies_heatmap(frq_df, show=False, max_len=None)
    assert isinstance(fig, go.Figure)

    # Test max_len behaviour.
    with pytest.raises(ValueError):
        api.plot_frequencies_heatmap(frq_df, show=False, max_len=len(frq_df) - 1)

    # Test index parameter - if None, should use dataframe index.
    fig = api.plot_frequencies_heatmap(frq_df, show=False, index=None, max_len=None)

    if "contig" in list(frq_df.columns):
        # Not unique.
        with pytest.raises(ValueError):
            api.plot_frequencies_heatmap(
                frq_df, show=False, index="contig", max_len=None
            )


def check_plot_frequencies_time_series(api, ds):
    # Trim things down a bit for speed.
    ds = ds.isel(variants=slice(0, 100))

    # Plot.
    fig = api.plot_frequencies_time_series(ds, show=False)

    # Test.
    assert isinstance(fig, go.Figure)


def check_plot_frequencies_time_series_with_taxa(api, ds):
    # Trim things down a bit for speed.
    ds = ds.isel(variants=slice(0, 100))

    taxa = list(ds.cohort_taxon.to_dataframe()["cohort_taxon"].unique())
    taxon = random.choice(taxa)

    # Plot with taxon.
    fig = api.plot_frequencies_time_series(ds, show=False, taxa=taxon)

    # Test taxon plot.
    assert isinstance(fig, go.Figure)

    # Plot with taxa.
    fig = api.plot_frequencies_time_series(ds, show=False, taxa=taxa)

    # Test taxa plot.
    assert isinstance(fig, go.Figure)


def check_plot_frequencies_time_series_with_areas(api, ds):
    # Trim things down a bit for speed.
    ds = ds.isel(variants=slice(0, 100))

    # Extract cohorts into a DataFrame.
    cohort_vars = [v for v in ds if str(v).startswith("cohort_")]
    df_cohorts = ds[cohort_vars].to_dataframe()

    # Pick a random area and areas from valid areas.
    cohorts_areas = df_cohorts["cohort_area"].dropna().unique().tolist()
    area = random.choice(cohorts_areas)
    areas = random.sample(cohorts_areas, random.randint(1, len(cohorts_areas)))

    # Plot with area.
    fig = api.plot_frequencies_time_series(ds, show=False, areas=area)

    # Test areas plot.
    assert isinstance(fig, go.Figure)

    # Plot with areas.
    fig = api.plot_frequencies_time_series(ds, show=False, areas=areas)

    # Test area plot.
    assert isinstance(fig, go.Figure)


def check_plot_frequencies_interactive_map(api, ds):
    import ipywidgets  # type: ignore

    # Trim things down a bit for speed.
    ds = ds.isel(variants=slice(0, 100))

    # Plot.
    fig = api.plot_frequencies_interactive_map(ds)

    # Test.
    assert isinstance(fig, ipywidgets.Widget)


def add_random_year(*, api):
    # Add a 'random_year' column to the sample_metadata, if it doesn't exist.

    # Get the existing sample metadata.
    sample_metadata_df = api.sample_metadata()

    # Only create the new column if it doesn't already exist.
    # Otherwise we'll get multiple columns with different suffixes, e.g. 'random_year_x' and 'random_year_y'.
    if "random_year" not in sample_metadata_df.columns:
        # Avoid "ValueError: No cohorts available" by selecting only a few different years at random.
        selected_years = random.sample(range(1900, 2100), 3)
        random_years_as_list = np.random.choice(selected_years, len(sample_metadata_df))
        random_years_as_period_index = pd.PeriodIndex(random_years_as_list, freq="Y")
        extra_metadata_df = pd.DataFrame(
            {
                "sample_id": sample_metadata_df["sample_id"],
                "random_year": random_years_as_period_index,
            }
        )
        api.add_extra_metadata(extra_metadata_df)

    return api
