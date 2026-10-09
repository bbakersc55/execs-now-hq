"""Who is in the demo (owner, 2026-10-08). Every person and company here is
fiction, and recognisably so: characters and companies from films and
television, none of them a real person. Every address is at `.example`, a
reserved domain that cannot receive mail."""

from __future__ import annotations

PRACTICE = "Summit Operations Partners"
SLUG = "summit-demo"
LEGAL_NAME = "Summit Operations Partners LLC"
DOMAIN = "summitops.example"
OWNER_NAME = "John Carter"
FOOTER = "Summit Operations Partners · Denver, CO"
PRIMARY = "#1F4E3D"          # deep green
ACCENT = "#B98A2E"           # warm gold, dark enough to pass against white too

#: (key, name, email, joined (year, month), what they keep or are paid)
ASSOCIATES = [
    ("ripley", "Ellen Ripley", "ellen.ripley@summitops.example", (2025, 5), 60),
    ("lasso", "Ted Lasso", "ted.lasso@summitops.example", (2026, 1), 60),
]
ASSISTANTS = [
    ("pam", "Pam Beesly", "pam.beesly@summitops.example", (2025, 8), 10),
    ("radar", "Walter O'Reilly", "walter.oreilly@summitops.example", (2026, 3), 10),
]

#: Company, industry, city, start (year, month), monthly retainer in dollars,
#: associate key or None, and its people: (first, last, title, portal) where
#: portal is "owner", "team", "team-never" (invited, never signed in) or "".
CLIENTS = [
    ("Acme Fasteners", "Manufacturing", "Tucson, AZ", (2025, 1), 4500, None, [
        ("Wiley", "Coyote", "Owner", "owner"),
        ("Marvin", "Martian", "Plant manager", "team"),
        ("Daffy", "Duckworth", "Purchasing lead", "")]),
    ("Wayne Industries", "Industrial services", "Gotham, NJ", (2025, 1), 8000, None, [
        ("Bruce", "Wayne", "Chief executive", "owner"),
        ("Lucius", "Fox", "Chief operating officer", "team"),
        ("Alfred", "Pennyworth", "Chief of staff", "team")]),
    ("Globex Logistics", "Logistics", "Cypress Creek, OR", (2025, 1), 3500, None, [
        ("Hank", "Scorpio", "President", "owner"),
        ("Frank", "Grimes", "Dispatch manager", "team-never")]),
    ("Initech Software", "Software", "Austin, TX", (2025, 1), 3000, None, [
        ("Bill", "Lumbergh", "Division vice president", "owner"),
        ("Milton", "Waddams", "Collections", "team"),
        ("Peter", "Gibbons", "Engineering lead", "")]),
    ("Pied Piper Compression", "Software", "Palo Alto, CA", (2025, 3), 2500, None, [
        ("Richard", "Hendricks", "Founder", "owner"),
        ("Jared", "Dunn", "Head of operations", "team")]),
    ("Stark Tool & Die", "Manufacturing", "Long Island, NY", (2025, 5), 5000, "ripley", [
        ("Pepper", "Potts", "Chief executive", "owner"),
        ("Happy", "Hogan", "Head of operations", "team"),
        ("Tony", "Stark", "Founder", "")]),
    ("Hooli Field Services", "Field services", "Mountain View, CA", (2025, 6), 4000,
     "ripley", [
         ("Gavin", "Belson", "Chief executive", "owner"),
         ("Denpok", "Singh", "Chief of staff", "team-never")]),
    ("Dunder Mifflin Paper", "Distribution", "Scranton, PA", (2025, 9), 2000, None, [
        ("Michael", "Scott", "Regional manager", "owner"),
        ("Dwight", "Schrute", "Assistant to the regional manager", "team")]),
    ("Vandelay Import-Export", "Distribution", "New York, NY", (2025, 11), 3500, None, [
        ("Art", "Vandelay", "Owner", "owner"),
        ("George", "Costanza", "Operations", "team")]),
    ("Cyberdyne Robotics", "Manufacturing", "Sunnyvale, CA", (2026, 2), 4500, "lasso", [
        ("Miles", "Dyson", "Director", "owner"),
        ("Sarah", "Connor", "Safety and compliance", "team")]),
    ("Sterling Cooper Creative", "Agency", "New York, NY", (2026, 5), 3500, "lasso", [
        ("Don", "Draper", "Creative director", "owner"),
        ("Joan", "Holloway", "Office manager", "team"),
        ("Peggy", "Olson", "Copy chief", "")]),
]

#: (first, last, title, company, stage code, days since they reached it,
#: the stages they came through on the way).
PROSPECTS = [
    ("Homer", "Simpson", "Safety inspector", "Springfield Power & Light",
     "initial_contact_made", 3, []),
    ("Leslie", "Knope", "Deputy director", "Pawnee Parks Supply", "initial_contact_made", 6, []),
    ("Philip", "Fry", "Delivery lead", "Planet Express", "initial_contact_made", 11, []),
    ("Walter", "Sobchak", "Owner", "Sobchak Security", "prospecting", 5,
     ["initial_contact_made"]),
    ("Cosmo", "Kramer", "Founder", "Kramerica Industries", "prospecting", 14,
     ["initial_contact_made"]),
    ("Bubba", "Blue", "Co-owner", "Bubba Gump Shrimp", "prospecting", 20,
     ["initial_contact_made"]),
    ("Moe", "Szyslak", "Owner", "Moe's Tavern Group", "follow_up_needed", 4,
     ["initial_contact_made", "prospecting"]),
    ("Selina", "Kyle", "Managing partner", "Kyle Jewelers", "follow_up_needed", 9,
     ["initial_contact_made"]),
    ("Dale", "Gribble", "Owner", "Dale's Dead-Bug", "follow_up_needed", 17,
     ["initial_contact_made", "prospecting"]),
    ("Gustavo", "Fring", "Owner", "Los Pollos Hermanos", "qualified", 7,
     ["initial_contact_made", "prospecting"]),
    ("Monica", "Geller", "Head chef and owner", "Central Perk Catering", "qualified", 12,
     ["initial_contact_made", "prospecting"]),
    ("Rocky", "Balboa", "Owner", "Mighty Mick's Gyms", "qualified", 19,
     ["initial_contact_made", "follow_up_needed"]),
    ("Willy", "Wonka", "Founder", "Wonka Confections", "consult_given", 2,
     ["initial_contact_made", "prospecting", "qualified"]),
    ("Lucille", "Bluth", "Chair", "Bluth Homes", "consult_given", 8,
     ["initial_contact_made", "qualified"]),
    ("Ron", "Swanson", "Owner", "Very Good Building Co", "consult_given", 15,
     ["initial_contact_made", "prospecting", "qualified"]),
    ("Montgomery", "Scott", "Chief engineer", "Enterprise Refit Yard", "consult_given", 1,
     ["initial_contact_made", "qualified"]),
    ("Jack", "Donaghy", "Vice president", "Sheinhardt Wig Company", "proposal_given", 4,
     ["initial_contact_made", "qualified", "consult_given"]),
    ("Olivia", "Pope", "Managing partner", "Pope & Associates", "proposal_given", 10,
     ["initial_contact_made", "prospecting", "qualified", "consult_given"]),
    ("Fred", "Sanford", "Owner", "Sanford & Son Salvage", "proposal_given", 16,
     ["initial_contact_made", "qualified", "consult_given"]),
    ("Carmela", "Soprano", "Owner", "Satriale's Provisions", "decision_making", 3,
     ["initial_contact_made", "qualified", "consult_given", "proposal_given"]),
    ("Jean-Luc", "Picard", "Owner", "Chateau Picard Vineyards", "decision_making", 9,
     ["initial_contact_made", "qualified", "consult_given", "proposal_given"]),
    ("Tyrion", "Lannister", "Master of coin", "Casterly Rock Mining", "decision_making", 13,
     ["initial_contact_made", "prospecting", "qualified", "consult_given",
      "proposal_given"]),
    ("Harvey", "Specter", "Name partner", "Pearson Specter", "negotiation", 2,
     ["initial_contact_made", "qualified", "consult_given", "proposal_given",
      "decision_making"]),
    ("Moira", "Rose", "Chair", "Rose Apothecary", "negotiation", 6,
     ["initial_contact_made", "qualified", "consult_given", "proposal_given"]),
    ("Fred", "Flintstone", "Crane operator, part owner", "Slate Rock & Gravel",
     "negotiation", 11,
     ["initial_contact_made", "prospecting", "qualified", "consult_given",
      "proposal_given", "decision_making"]),
    ("Cosmo", "Spacely", "Owner", "Spacely Sprockets", "closed_lost", 12,
     ["initial_contact_made", "qualified", "consult_given", "proposal_given"]),
    ("Eldon", "Tyrell", "Founder", "Tyrell Replicas", "closed_lost", 26,
     ["initial_contact_made", "qualified", "consult_given"]),
    ("Krusty", "Clown", "Owner", "Krusty Burger", "closed_lost", 41,
     ["initial_contact_made", "prospecting", "qualified", "consult_given",
      "proposal_given"]),
    ("George", "Jetson", "Digital index operator", "Cogswell Cogs", "nurture", 18,
     ["initial_contact_made", "prospecting"]),
    ("Charles", "Kane", "Publisher", "Inquirer Print Works", "nurture", 30,
     ["initial_contact_made", "qualified", "consult_given"]),
    ("Norma", "Desmond", "Owner", "Sunset Studios Rentals", "nurture", 47,
     ["initial_contact_made", "prospecting", "qualified"]),
]

#: (first, last, title, firm, cadence, enrolled). Most are on the touches.
PARTNERS = [
    ("Ben", "Wyatt", "CPA", "Wyatt Accounting", "monthly", True),
    ("Oscar", "Martinez", "Senior accountant", "Martinez & Malone CPAs", "quarterly", True),
    ("Skyler", "White", "Bookkeeper", "White Ledger Services", "bimonthly", True),
    ("Saul", "Goodman", "Attorney", "Goodman Law", "quarterly", True),
    ("Kim", "Wexler", "Attorney", "Wexler Legal", "monthly", True),
    ("Atticus", "Finch", "Attorney", "Finch Law Office", "quarterly", True),
    ("Perry", "Mason", "Attorney", "Mason & Street", "quarterly", False),
    ("Jessica", "Pearson", "Managing partner", "Pearson Hardman", "bimonthly", True),
    ("Elle", "Woods", "Attorney", "Woods Employment Law", "monthly", True),
    ("George", "Bailey", "Commercial banker", "Bailey Building & Loan", "monthly", True),
    ("Nick", "Carraway", "Bond specialist", "West Egg Capital", "quarterly", True),
    ("Jay", "Gatsby", "Private banker", "East Egg Trust", "quarterly", False),
    ("Thurston", "Howell", "Wealth advisor", "Howell Wealth", "bimonthly", True),
    ("Lovey", "Howell", "Wealth advisor", "Howell Wealth", "bimonthly", True),
    ("Scrooge", "McDuck", "Investor", "McDuck Capital", "quarterly", True),
    ("Jerry", "Maguire", "Agent", "Maguire Sports Management", "monthly", True),
    ("Ari", "Gold", "Agent", "Gold Talent", "quarterly", False),
    ("Liz", "Lemon", "Executive producer", "Lemon Media", "bimonthly", True),
    ("Leslie", "Winkle", "Fractional CFO", "Winkle Finance", "monthly", True),
    ("Angela", "Martin", "Fractional CFO", "Martin Controllership", "monthly", True),
    ("Toby", "Flenderson", "HR consultant", "Flenderson HR", "bimonthly", True),
    ("Holly", "Flax", "HR consultant", "Flax People Ops", "monthly", True),
    ("Joan", "Clayton", "Fractional CMO", "Clayton Marketing", "monthly", True),
    ("Roger", "Sterling", "Fractional CMO", "Sterling Growth", "quarterly", True),
    ("Frasier", "Crane", "Executive coach", "Crane Coaching", "bimonthly", True),
    ("Niles", "Crane", "Executive coach", "Crane Coaching", "bimonthly", False),
    ("Mary", "Poppins", "Executive coach", "Practically Perfect Coaching", "quarterly", True),
    ("Clark", "Kent", "Business reporter", "Daily Planet", "quarterly", True),
    ("Lois", "Lane", "Business editor", "Daily Planet", "quarterly", False),
    ("Diana", "Prince", "Insurance broker", "Themyscira Insurance", "monthly", True),
    ("Flo", "Castleberry", "Insurance broker", "Mel's Insurance Group", "bimonthly", True),
    ("Rebecca", "Welton", "Peer group chair", "Richmond Owners Forum", "monthly", True),
    ("Leslie", "Higgins", "Peer group chair", "Richmond Owners Forum", "quarterly", True),
    ("Marge", "Gunderson", "Chamber president", "Brainerd Chamber of Commerce",
     "quarterly", True),
    ("Andy", "Dufresne", "Banker", "Shawshank Savings", "monthly", True),
    ("Ellis", "Redding", "Procurement broker", "Redding Supply", "quarterly", False),
    ("Marty", "Byrde", "Financial planner", "Byrde Financial", "bimonthly", True),
    ("Tom", "Hagen", "Attorney", "Hagen Counsel", "quarterly", True),
]

#: (first, last, title, firm, service category, 1099 payee)
VENDORS = [
    ("Erlich", "Bachman", "Owner", "Aviato Web Studio", "Website and SEO", True),
    ("Maurice", "Moss", "Owner", "Reynholm IT Support", "IT support", False),
    ("Roy", "Trenneman", "Technician", "Reynholm IT Support", "IT support", False),
    ("Stanley", "Hudson", "Owner", "Hudson Print & Sign", "Printing", False),
    ("Kenneth", "Parcell", "Owner", "Parcell Event Staffing", "Events", False),
]
