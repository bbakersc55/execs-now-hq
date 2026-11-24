"""The approved change list for the Rental Management Agreement, V.2
(approved by Bryan on 2026-11-23; A8, A9 and A12 to A16 as changed on
2026-11-24), as data for apps/agreements/textcheck.py.

Every difference between the 2014 PDF and the template is one of these. The
words in brackets are where the agreement's variables go; the comparison
renders the template with the same brackets (`render.compare_text`).
"""

from ..textcheck import Change

# A8: the owner's page, as in the brief (owner, 2026-11-23), in two headed parts
# (owner, 2026-11-24): the property address comes from the opening, Sleeps is
# asked, ADDRESS reads MAILING ADDRESS, BUSINESS PHONE reads ALTERNATE PHONE
# (optional), and the emergency contact's ADDRESS and TELEPHONE read MAILING
# ADDRESS and PHONE.
OWNER_SECTION = (
    "Unit Information "
    "PROPERTY ADDRESS: [property address] "
    "# Bedrooms: [bedrooms] # Bathrooms: [bathrooms] Sq Footage: [square footage] "
    "Sleeps: [sleeps] "
    "Owner Information "
    "OWNER OF RECORD: [owner of record] "
    "SIGNER’S NAME AND TITLE (if the Owner is a company or trust): [signer name and title] "
    "PHONE: [phone] EMAIL ADDRESS: [email] "
    "MAILING ADDRESS: [mailing address] "
    "CITY: [city] STATE: [state] ZIP: [zip] "
    "ALTERNATE PHONE (optional): [alternate phone] "
    "If only one owner, please list another person we could contact in case of an emergency. "
    "NAME: [emergency contact name] "
    "MAILING ADDRESS: [emergency contact address] "
    "PHONE: [emergency contact phone]"
)

# A9: the signatures. The owner's block is repeated for each owner, up to four
# (owner, 2026-11-24), each with the owner's printed name under it; "condo"
# reads "Unit".
SIGNATURES = (
    "THE PARTIES HERETO HAVE EXECUTED THIS AGREEMENT. "
    "MANAGER SKYRUN PARK CITY "
    "BY: [Manager signature] DATE: [Manager date] "
    "NAME: Michael LeClerc, President "
    "By signing below, you are indicating that you own all or part of the unit. You are also "
    "indicating that ANY AND ALL additional owners have signed below. "
    "OWNER BY: [Owner signature] Signature DATE: [Owner date] NAME: [owner name] "
    "(ALL owners of Unit must sign)"
)

# A16: Exhibit A's other features (owner, 2026-11-24, as written).
OTHER_FEATURES = (
    "Other Features: After signing, you will be able to list your Unit's amenities and unique "
    "features on the onboarding form, and send any photos you would like us to use in "
    "addition to the ones we take."
)

CHANGES = [
    # A. Terms and layout
    Change("A1", "Opening line", find="this ___ day of ______________, _____",
           to="[agreement date]",
           note="Filled with the countersigning date; before that it reads as dated on "
                "SkyRun's signature."),
    Change("A2", "Opening, the property",
           find="the property ______________________, in Park City Utah, situated in Park City, "
                "Utah, (hereafter, “Unit”)",
           to="the property located at [property address] (hereafter, “Unit”)"),
    Change("A3", "Section 7", find="$55/hour for labor", to="$75/hour for labor"),
    Change("A3", "Section 7", find="$55/hr of our time", to="$75/hr of our time"),
    Change("A4", "Section 14", find="(currently costs $395 installed)",
           to="(currently costs up to $395 installed)"),
    Change("A5", "Section 15", to="",
           note="70% and 30% become the owner and manager percents staff set; the default 70 "
                "and 30 render as the PDF's words."),
    Change("A6", "Section 19",
           find="As a guideline, manager’s cleaning fees are generally $175 for a studio",
           until="Individual homes are generally more.",
           to="Cleaning fees depend on the size of the property and the number of bedrooms, "
              "beds and bathrooms, and will be finalized once a quote has been obtained."),
    Change("A7", "Section 30", after="30) ADDITIONAL ITEMS:", to="[section 30]",
           note="The fee clause when any fee is above $0, then the additional items; "
                "\"None.\" when both are empty."),
    Change("A8", "Owner's page", find="(PLEASE PRINT CLEARLY)", until="TELEPHONE:",
           to=OWNER_SECTION),
    Change("A9", "Signatures", find="THE PARTIES HERETO HAVE EXECUTED THIS AGREEMENT.",
           until="ALL owners of condo must sign)", to=SIGNATURES),
    # A10 (the footer) and A11 (the signing record) are outside the agreement's
    # words: tests/test_agreement_text.py checks them on the PDF itself.

    # Exhibit A's quantities follow Sleeps (owner, 2026-11-24): the rules are in
    # apps/agreements/exhibit_a.py. They replace C38 and C41, whose lines are gone.
    Change("A12", "Exhibit A, dinnerware",
           find="8 place settings (40 pieces for Studios, 1 and 2 bedrooms)",
           until="12 place settings (60 pieces for 3 and 4 bedrooms)",
           to="[place settings] place settings ([dinnerware pieces] pieces)"),
    Change("A13", "Exhibit A, flatware",
           find="8 place settings (for Studios, 1 and 2 bedrooms, 12 place settings for 3 and "
                "4 bedrooms)",
           to="[place settings] place settings"),
    Change("A14", "Exhibit A, teaspoons",
           find="Teaspoons (12 for Studios, 1 and 2 bedrooms) (16 for 3 and 4 bedrooms",
           to="Teaspoons ([teaspoons])"),
    Change("A15", "Exhibit A, glassware",
           find="Juice (8 for Studios, 1 and 2 bedrooms, 12 for 3 and 4 bedrooms)",
           to="Juice ([place settings])"),
    Change("A15", "Exhibit A, glassware",
           find="Wine (8 for Studios, 1 and 2 bedrooms, 12 for 3 and 4 bedrooms)",
           to="Wine ([place settings])"),
    Change("A15", "Exhibit A, glassware",
           find="Highball (8 for Studios, 1 and 2 bedrooms, 12 for 3 and 4 bedrooms)",
           to="Highball ([place settings])"),
    Change("A15", "Exhibit A, glassware",
           find="Old Fashioned (8 for Studios, 1 and 2 bedrooms, 12 for 3 and 4 bedrooms)",
           to="Old Fashioned ([place settings])"),
    Change("A15", "Exhibit A, place mats",
           find="Place mats (set of 8 for Studios, 1 and 2 bedrooms, set of 12 for 3 and 4 "
                "bedrooms)",
           to="Place mats (set of [place mats])"),
    Change("A16", "Exhibit A, other features", find="Other Features (optional):",
           until="in addition to the ones we take.", to=OTHER_FEATURES),

    # C. Typo corrections
    Change("C1", "Section 1", find="without Managers’ staff involvement",
           to="without Manager’s staff involvement"),
    Change("C2", "Section 1", find="sells, closes and or Manager enters",
           to="sells, closes and/or Manager enters"),
    Change("C3", "Section 4", find="consult with owner", to="consult with Owner"),
    Change("C4", "Section 4", find="Owner and manager will set", to="Owner and Manager will set"),
    Change("C5", "Section 5 heading", find="MANAGERS REPRESENTATION",
           to="MANAGER’S REPRESENTATION"),
    Change("C6", "Section 5", find="and, that in securing occupancy",
           to="and that, in securing occupancy"),
    Change("C7", "Section 6 heading", find="OWNER USE EFFECTS RENT", to="OWNER USE AFFECTS RENT"),
    Change("C8", "Section 7", find="hvac, etc) ,", to="HVAC, etc.),"),
    Change("C9", "Section 7", find="incurred by the manager", to="incurred by the Manager"),
    Change("C10", "Section 7", find="slowly dripping, etc)", to="slowly dripping, etc.)"),
    Change("C11", "Section 7", find="adversely effects the rentability",
           to="adversely affects the rentability"),
    Change("C12", "Section 7", find="bill the owner", to="bill the Owner"),
    Change("C13", "Section 9", find="disperse any rents", to="disburse any rents"),
    Change("C13", "Section 9", find="will disperse rents", to="will disburse rents"),
    Change("C14", "Section 11", find="homeowners associations dues",
           to="homeowners association dues"),
    Change("C15", "Section 11, every occurrence", find="hottub", to="hot tub"),
    Change("C15", "Section 11, every occurrence", find="Hottub", to="Hot tub"),
    Change("C16", "Section 11", find="$ 200", to="$200"),
    Change("C17", "Section 13", find="marking owners areas", to="marking Owner’s areas"),
    Change("C18", "Section 13", find="off-limit to guests", to="off-limits to guests"),
    Change("C19", "Section 13", find="TV operation instructions) a small area",
           to="TV operation instructions), and a small area"),
    Change("C20", "Section 14", find="owners-use keys", to="Owner-use keys"),
    Change("C21", "Section 15", find="and manager shall receive", to="and Manager shall receive"),
    Change("C22", "Section 15", find="under this Agreement, The unit rental revenue",
           to="under this Agreement. The Unit rental revenue"),
    Change("C23", "Section 15", find="rental income to owners", to="rental income to Owner"),
    Change("C24", "Section 15", find="to insure the validity of funds",
           to="to ensure the validity of funds"),
    Change("C25", "Section 17", find="it’s representatives", to="its representatives"),
    Change("C25", "Section 17, twice", find="it’s best efforts", to="its best efforts"),
    Change("C26", "Section 17", find="until dispersal", to="until disbursement"),
    Change("C27", "Section 18", find="(owners portal)", to="(owner’s portal)"),
    Change("C28", "Section 19", find="Owner's guest who occupy", to="Owner's guests who occupy"),
    Change("C29", "Section 19", find="firestarters", to="fire starters"),
    Change("C30", "Section 20", find="to their management inventory",
           to="to its management inventory"),
    Change("C31", "Section 26", find="it's contents", to="its contents"),
    Change("C32", "Section 26", find="so as avoid negative impact on Owners rental commission",
           to="so as to avoid negative impact on Owner’s rental commission"),
    Change("C33", "Section 26", find="even of items wear out", to="even if items wear out"),
    Change("C34", "Section 26", find="these are broke by", to="these are broken by"),
    Change("C35", "Section 27 heading", find="INDEMNIFICATION:.", to="INDEMNIFICATION:"),
    Change("C36", "Section 28", find="in writing to contrary", to="in writing to the contrary"),
    Change("C37", "Section 29", find="softener salt replenishing ect.",
           to="softener salt replenishing, etc."),
    Change("C39", "Exhibit A, bedding",
           find="“Triple Sheet Method for sanitary and professionally made beds.provides other "
                "linens and towels)",
           to="“Triple Sheet Method” for sanitary and professionally made beds. SkyRun provides "
              "other linens and towels.)"),
    Change("C40", "Exhibit A", find="Hi Definition Cable Ready TV's",
           to="High-Definition Cable-Ready TVs"),
]

# B. The fee clause, word for word (owner, 2026-11-23).
FEE_CLAUSE = (
    "MINIMUM REVENUE MANAGEMENT FEE: For each calendar month in the periods listed below, if "
    "the Unit's rental revenue, as defined in Section 15, is less than the revenue threshold "
    "shown for that period, Owner shall pay Manager the management fee shown for that period. "
    "No fee is due under this paragraph for a month in which the Unit's rental revenue meets "
    "or exceeds the threshold. Any fee due will appear on the Owner's Statement and will be "
    "deducted or billed as provided in Section 9."
)
FEE_LINE = "{period}: revenue threshold ${threshold} per month; fee ${fee} per month"
PERIODS = (("winter", "December 1 – March 31"), ("summer", "April 1 – July 31"),
           ("fall", "August 1 – November 30"))
FOOTER_VERSION = "V.2 – November 2026"
FOOTER_COPYRIGHT = "© Park City Ski Chalets, LLC"
