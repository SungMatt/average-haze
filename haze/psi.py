"""NEA Pollutant Standards Index (PSI) conversion for PM2.5.

Source: National Environment Agency, "Computation of the Pollutant Standards
Index (PSI)", last updated March 2014.
https://www.haze.gov.sg/docs/default-source/faq/computation-of-the-pollutant-standards-index-(psi).pdf

Each pollutant sub-index is a segmented linear function mapping ambient
concentration onto 0-500. NEA's published PM2.5 band table is:

    PSI band     24-hr PM2.5 (ug/m3)
    0 - 50       0 - 12
    51 - 100     13 - 55
    101 - 200    56 - 150
    201 - 300    151 - 250
    301 - 400    251 - 350
    401 - 500    351 - 500

The bands are stated as integer ranges, but the interpolation in Equation 1
joins the segment endpoints continuously -- NEA's own worked example converts
40 ug/m3 using the segment (12, 50) -> (55, 100), giving 83.  The node list
below reproduces that.
"""

# (concentration ug/m3, sub-index) breakpoint nodes, ascending.
PM25_BREAKPOINTS = [
    (0.0, 0),
    (12.0, 50),
    (55.0, 100),
    (150.0, 200),
    (250.0, 300),
    (350.0, 400),
    (500.0, 500),
]

# (inclusive lower bound, label). NEA descriptor bands.
PSI_BANDS = [
    (0, "Good"),
    (51, "Moderate"),
    (101, "Unhealthy"),
    (201, "Very Unhealthy"),
    (301, "Hazardous"),
]


def pm25_to_psi(concentration):
    """Convert a PM2.5 concentration (ug/m3) to its PSI sub-index.

    Implements NEA Equation 1:
        Ii = (Ii,j+1 - Ii,j) / (Xi,j+1 - Xi,j) * (Xi - Xi,j) + Ii,j
    Returns a float; NEA reports the rounded integer. Concentrations above the
    top breakpoint are capped at 500, which is where NEA's scale ends.
    """
    if concentration is None:
        return None
    x = float(concentration)
    if x < 0:
        raise ValueError("PM2.5 concentration cannot be negative: %r" % concentration)
    if x >= PM25_BREAKPOINTS[-1][0]:
        return 500.0
    for (x_lo, i_lo), (x_hi, i_hi) in zip(PM25_BREAKPOINTS, PM25_BREAKPOINTS[1:]):
        if x_lo <= x <= x_hi:
            return (i_hi - i_lo) / (x_hi - x_lo) * (x - x_lo) + i_lo
    raise ValueError("concentration outside breakpoint table: %r" % concentration)


def psi_band(index):
    """Return the NEA descriptor for a PSI value."""
    if index is None:
        return None
    label = PSI_BANDS[0][1]
    for lower, name in PSI_BANDS:
        if round(index) >= lower:
            label = name
    return label


def psi_to_pm25(index):
    """Inverse of pm25_to_psi: the concentration that produces a given PSI."""
    if index is None:
        return None
    i = float(index)
    if i >= 500:
        return PM25_BREAKPOINTS[-1][0]
    for (x_lo, i_lo), (x_hi, i_hi) in zip(PM25_BREAKPOINTS, PM25_BREAKPOINTS[1:]):
        if i_lo <= i <= i_hi:
            return (x_hi - x_lo) / (i_hi - i_lo) * (i - i_lo) + x_lo
    raise ValueError("index outside breakpoint table: %r" % index)
