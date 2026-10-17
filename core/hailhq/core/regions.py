"""US states and Canadian provinces for the number search's ``region``.

One list for the API (``NumberQuoteRequest`` rejects any other code) and for
every client (``GET /numbers/regions``). In the US and Canada a city name
repeats across states, so a city search there needs one of these codes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# country -> {code: name}. Codes are the ISO 3166-2 suffixes the carriers use.
REGIONS: dict[str, dict[str, str]] = {
    "US": {
        "AL": "Alabama",
        "AK": "Alaska",
        "AZ": "Arizona",
        "AR": "Arkansas",
        "CA": "California",
        "CO": "Colorado",
        "CT": "Connecticut",
        "DE": "Delaware",
        "DC": "District of Columbia",
        "FL": "Florida",
        "GA": "Georgia",
        "HI": "Hawaii",
        "ID": "Idaho",
        "IL": "Illinois",
        "IN": "Indiana",
        "IA": "Iowa",
        "KS": "Kansas",
        "KY": "Kentucky",
        "LA": "Louisiana",
        "ME": "Maine",
        "MD": "Maryland",
        "MA": "Massachusetts",
        "MI": "Michigan",
        "MN": "Minnesota",
        "MS": "Mississippi",
        "MO": "Missouri",
        "MT": "Montana",
        "NE": "Nebraska",
        "NV": "Nevada",
        "NH": "New Hampshire",
        "NJ": "New Jersey",
        "NM": "New Mexico",
        "NY": "New York",
        "NC": "North Carolina",
        "ND": "North Dakota",
        "OH": "Ohio",
        "OK": "Oklahoma",
        "OR": "Oregon",
        "PA": "Pennsylvania",
        "RI": "Rhode Island",
        "SC": "South Carolina",
        "SD": "South Dakota",
        "TN": "Tennessee",
        "TX": "Texas",
        "UT": "Utah",
        "VT": "Vermont",
        "VA": "Virginia",
        "WA": "Washington",
        "WV": "West Virginia",
        "WI": "Wisconsin",
        "WY": "Wyoming",
    },
    "CA": {
        "AB": "Alberta",
        "BC": "British Columbia",
        "MB": "Manitoba",
        "NB": "New Brunswick",
        "NL": "Newfoundland and Labrador",
        "NS": "Nova Scotia",
        "NT": "Northwest Territories",
        "NU": "Nunavut",
        "ON": "Ontario",
        "PE": "Prince Edward Island",
        "QC": "Quebec",
        "SK": "Saskatchewan",
        "YT": "Yukon",
    },
}


class NumberRegion(BaseModel):
    country_code: str = Field(description="ISO alpha-2 country code: US or CA.")
    code: str = Field(
        description="Two-letter state or province code, such as AZ. Send it as region."
    )
    name: str = Field(description="State or province name, such as Arizona.")


class NumberRegionsResponse(BaseModel):
    regions: list[NumberRegion] = Field(
        description="Every state and province the number search accepts as region."
    )


def regions_response() -> NumberRegionsResponse:
    return NumberRegionsResponse(
        regions=[
            NumberRegion(country_code=country, code=code, name=name)
            for country, names in REGIONS.items()
            for code, name in names.items()
        ]
    )
