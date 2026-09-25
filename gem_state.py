"""Resolve the Indian state for a GeM bid from its department / ministry text.

No network calls, no PDF parsing -- pure string matching on data the listing
API already returns. Many GeM buyers are central bodies (Military Affairs,
Atomic Energy, Indian Railways) that are genuinely national, so a blank state
is a correct answer, not a failure.
"""
import re

# Canonical names. Longest-first matching avoids "Bihar" hitting inside other
# words and ensures "Himachal Pradesh" wins over a bare "Pradesh".
STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Delhi", "Ladakh", "Puducherry", "Chandigarh", "Goa",
]

# Variants and older names that appear in GeM department strings.
ALIASES = {
    "jammu and kashmir": "Jammu & Kashmir",
    "jammu & kashmir": "Jammu & Kashmir",
    "jammu": "Jammu & Kashmir",
    "kashmir": "Jammu & Kashmir",
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "uttaranchal": "Uttarakhand",
    "nct of delhi": "Delhi",
    "new delhi": "Delhi",
    "andaman": "Andaman & Nicobar",
    "nicobar": "Andaman & Nicobar",
    "lakshadweep": "Lakshadweep",
    "dadra": "Dadra & Nagar Haveli",
    "daman": "Daman & Diu",
    "telengana": "Telangana",
    "tamilnadu": "Tamil Nadu",
    "chattisgarh": "Chhattisgarh",
}

# Cities/bodies that unambiguously imply a state.
CITY_HINTS = {
    "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra",
    "bengaluru": "Karnataka", "bangalore": "Karnataka", "mysuru": "Karnataka",
    "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu",
    "hyderabad": "Telangana", "kolkata": "West Bengal",
    "ahmedabad": "Gujarat", "surat": "Gujarat",
    "jaipur": "Rajasthan", "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh",
    "bhopal": "Madhya Pradesh", "indore": "Madhya Pradesh",
    "patna": "Bihar", "guwahati": "Assam", "bhubaneswar": "Odisha",
    "thiruvananthapuram": "Kerala", "kochi": "Kerala",
}


def state_from_text(department="", ministry=""):
    """Return (state, source) or ('', ''). source is 'name' or 'city'."""
    blob = " ".join(t or "" for t in (department, ministry))
    low = blob.lower()

    for alias, canon in sorted(ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in low:
            return canon, "name"

    for s in sorted(set(STATES), key=len, reverse=True):
        if re.search(r"\b" + re.escape(s.lower()) + r"\b", low):
            return s, "name"

    for city, st in CITY_HINTS.items():
        if re.search(r"\b" + city + r"\b", low):
            return st, "city"

    return "", ""


def resolve(department="", ministry=""):
    return state_from_text(department, ministry)
