from mongoengine import connect, Q
from app.models.schemas import Company, SebiChecklist, BseChecklist, StandardChecklist, Litigation
import os
from dotenv import load_dotenv

load_dotenv()

connect(db=os.getenv("MONGO_DB"), host=os.getenv("MONGO_URI"))

# 1) Find all CINs that have more than one Company
pipeline = [
    {"$group": {
        "_id": "$corporate_identity_number",
        "ids": {"$push": "$_id"},
        "count": {"$sum": 1}
    }},
    {"$match": {"count": {"$gt": 1}}}
]

for dup in Company.objects.aggregate(*pipeline):
    cin = dup["_id"]
    ids = dup["ids"]

    # 2) Score each candidate by total related docs
    def score(cid):
        return sum([
            SebiChecklist.objects(company_id=cid).count(),
            BseChecklist.objects(company_id=cid).count(),
            StandardChecklist.objects(company_id=cid).count(),
            Litigation.objects(company_id=cid).count(),
        ])

    best_id = max(ids, key=score)
    print(f"Keeping {best_id} for CIN={cin}; deleting {set(ids)-{best_id}}")

    # 3) Delete the losers
    for cid in ids:
        if cid != best_id:
            Company.objects(id=cid).first().delete()
