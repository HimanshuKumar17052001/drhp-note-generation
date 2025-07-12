
from mongoengine import Document,DynamicDocument, StringField, IntField, ListField, ReferenceField, BinaryField
from mongoengine import EmailField, DictField, EmbeddedDocumentListField, BooleanField
from mongoengine import EmbeddedDocument, URLField, DateTimeField, EmbeddedDocumentField
from mongoengine import FloatField
from openai import AzureOpenAI
import os
from qdrant_client import QdrantClient
from qdrant_client.http import models
from app.services.qdrant_utils import write_to_qdrant, generate_vector, get_collection_name, create_qdrant_collection
from typing import List
import uuid
import time
import logging
from bson import ObjectId
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
from qdrant_client.http import models as rest_models
from fastembed import SparseTextEmbedding
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from qdrant_client.http.models import SparseIndexParams
import requests

from app.utils.splade_client import splade_sparse



PAGES_COLLECTION_NAME = "os_pages_1024_new"
load_dotenv()



logging.basicConfig(filename="qdrant_failures.log", level=logging.ERROR, 
                    format="%(asctime)s - %(levelname)s - %(message)s")



try:
    qdrant_url = os.getenv("QDRANT_URL")
    print(f"Connecting to Qdrant at {qdrant_url}")
    qdrant_client = QdrantClient(url=qdrant_url, timeout=60)
except Exception as e:
    print(f"Qdrant connection ❌: {e}")
    qdrant_client = None
    
    
if qdrant_client.info():
    print("Qdrant client connected in schemas.py ✅")
else:
    print("Qdrant client ❌")
        


STATUS_TYPES = ['FLAGGED', 'NOT FLAGGED', 'REQUIRES FURTHER REVIEW']
CATEGORY_TYPES = ['FRONT PAGE CHECKS', 'CAPITAL STRUCTURE CHECKS', 'RISK FACTOR CHECKS']
RISK_LEVEL_TYPES = ['LOW', 'MEDIUM', 'HIGH']
PROCESSING_STATUS_TYPES = ['PENDING', 'COMPLETED', 'FAILED']
PROCESS_NAME_TYPES = ['SEBI_CHECKLIST', 'BSE_CHECKLIST', 'STANDARD_CHECKLIST', 'LITIGATION', 'SECTION_CREATION']




class PeopleAndEntities(DynamicDocument):
    company_id = ReferenceField('Company')
    name = StringField(required=True)
    type = StringField(required=True)
    status = StringField(required=True, choices=STATUS_TYPES)
    summary_analysis = DictField()


class Company(DynamicDocument):
    name = StringField(required=True)
    pages = ListField(ReferenceField('Pages'))
    corporate_identity_number = StringField(required=True)
    drhp_file_url = StringField(required=True)
    people_and_entities = ListField(ReferenceField('PeopleAndEntities'))
    qr_code_url = StringField(required=True)
    website_link = StringField(required=True)

    def delete(self, *args, **kwargs):
        # Delete all associated pages (including from Qdrant)
        for page in self.pages:
            page.delete()

        # Delete all associated people and entities
        for entity in self.people_and_entities:
            entity.delete()

        SebiChecklist.objects(company_id=self.id).delete()

        # Delete associated BSE checklist items
        BseChecklist.objects(company_id=self.id).delete()

        # Delete associated Standard checklist items
        StandardChecklist.objects(company_id=self.id).delete()

        # Delete associated Litigation records
        Litigation.objects(company_id=self.id).delete()

        # Finally delete the company itself
        super().delete(*args, **kwargs)


class Regulation(DynamicDocument):
    regulation_number = StringField(required=True)
    name = StringField(required=True)
    content = StringField(required=True)
    document_url = StringField(required=True)
    content_last_updated = DateTimeField(required=True)
    document_name = StringField(required=True)


class SebiChecklist(DynamicDocument):
    company_id = ReferenceField('Company')
    regulation_mentioned = StringField()
    particulars = StringField(required=True)
    summary_analysis = StringField(required=True)
    flag_status = BooleanField(required=True)
    status = StringField(required=True, choices=STATUS_TYPES)
    page_number = StringField()


class BseChecklist(DynamicDocument):
    company_id = ReferenceField('Company')
    regulation_mentioned = StringField()
    particulars = StringField(required=True)
    summary_analysis = StringField(required=True)
    flag_status = BooleanField(required=True)
    status = StringField(required=True, choices=STATUS_TYPES)
    page_number = StringField()


class StandardChecklist(DynamicDocument):
    company_id = ReferenceField('Company')
    heading = StringField(required=True)
    checklist_points = StringField(required=True)
    remarks = StringField()  # Made optional
    summary_analysis = StringField()  # Made optional
    status = StringField(required=True, choices=STATUS_TYPES)
    page_number = StringField()


class User(DynamicDocument):
    name = StringField()
    username = StringField(required=True)
    email = StringField(required=True)
    password = BinaryField(required=True)

    

class Litigation(DynamicDocument):
    company_id = ReferenceField('Company')
    director_name = StringField(required=True)
    position_in_company = StringField(required=True)
    case_count = IntField(required=True, default=0)
    status_of_case = StringField(required=True, choices=STATUS_TYPES)
    details_of_case = StringField()
    risk_level = StringField(required=True, choices=RISK_LEVEL_TYPES)



class Pages(DynamicDocument):
    company = ReferenceField('Company')
    page_number_pdf = IntField(required=True)
    page_number_drhp = StringField(required=True)
    page_content = StringField(required=True)
    facts= ListField(StringField(), default=[])
    queries = ListField(StringField(), default=[])




    def _ensure_collection(self):
        
        existing = {c.name for c in qdrant_client.get_collections().collections}
        if PAGES_COLLECTION_NAME in existing:
            return                                                # already there

        qdrant_client.create_collection(
            collection_name=PAGES_COLLECTION_NAME,
            vectors_config={
                "dense": rest_models.VectorParams(
                    size=1024,
                    distance=rest_models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                "sparse": rest_models.SparseVectorParams(
                    index=rest_models.SparseIndexParams()
                )
            }
        )
        # single keyword payload index on company_id
        qdrant_client.create_payload_index(
            collection_name=PAGES_COLLECTION_NAME,
            field_name="company_id",
            field_schema=models.KeywordIndexParams(type="keyword")
        )

        try:
            qdrant_client.create_payload_index(
                collection_name=PAGES_COLLECTION_NAME,
                field_name="page_content",
                field_schema=models.TextIndexParams(
                    type="text",
                    tokenizer=models.TextTokenizerType.PREFIX,
                    min_token_len=2,
                    lowercase=True
                )
            )
        except:
            logging.info(f"Full-text index already exists for text")
            pass
        logging.info(f"[Qdrant] Created collection `{PAGES_COLLECTION_NAME}` with required indexes")

    def _make_point(self,in_docker: bool = False):
        """
        Build the Qdrant PointStruct (dense + sparse embeds + payload)
        """
        
        # ----- Dense embedding on queries -------------------------------------------------------
        query_text = " ".join(self.queries) if isinstance(self.queries, (list, tuple)) else str(self.queries)
        dense = generate_vector(query_text)

        # ----- Sparse embedding on facts --------------------------------------------------------
        facts_text = " ".join(self.facts) if isinstance(self.facts, (list, tuple)) else str(self.facts)
        # sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
        # sparse_emb = list(sparse_model.embed(facts_text))[0]    # returns CSR-like structure
        # sparse_vec = rest_models.SparseVector(
        #     indices=sparse_emb.indices.tolist(),
        #     values=sparse_emb.values.tolist()
        # )
        sparse_dict = splade_sparse(facts_text, in_docker=in_docker)

        sparse_vec = rest_models.SparseVector(
            indices=list(sparse_dict.keys()),
            values=list(sparse_dict.values())
        )


        # ----- Assemble point ------------------------------------------------------------------
        point_id = uuid.uuid5(uuid.NAMESPACE_DNS,
                              f"{self.company.id}-{self.page_number_pdf}")
        return models.PointStruct(
            id=str(point_id),
            vector={"dense": dense,
                    "sparse": sparse_vec},
            payload={
                "company_id":          str(self.company.id),
                "page_number_pdf":     int(self.page_number_pdf),
                "page_number_drhp":    str(self.page_number_drhp),
                "page_content":        str(self.page_content),
                "facts":               self.facts,
                "queries":             self.queries,
            }
        )

    def save(self, update_qdrant=False, in_docker=False, *args, **kwargs):
        super().save(*args, **kwargs)

        if update_qdrant:
            start = time.time()  # ⬅️ Define timing here
            try:
                self._ensure_collection()
                point = self._make_point(in_docker=in_docker)
                qdrant_client.upsert(collection_name=PAGES_COLLECTION_NAME, points=[point])
                logging.info(
                    f"[Qdrant] Upserted page (PDF {self.page_number_pdf} / DRHP {self.page_number_drhp}) "
                    f"for company `{self.company.id}` in {time.time() - start:.2f}s"
                )
            except Exception as exc:
                logging.error(f"[Qdrant] Failed to upsert page (company={self.company.id}, "
                            f"pdf={self.page_number_pdf}): {exc}", exc_info=True)

        return self


    @classmethod
    def search(cls, query_text: str, company_id: str, limit: int = 5, in_docker=False):
        """
        Hybrid dense+sparse search against the same Qdrant collection used by `.save()`.
        Returns a list of ScoredPoint (from `qdrant_client.http.models.ScoredPoint`).

        Parameterss
        ----------
        query_text : str
            Natural-language query.
        company_id : str
            The Company ID to filter on (must match the payload field "company_id").
        limit : int
            How many final hits to return (after fusion).

        Example
        -------
            hits = Pages.search(
                query_text="find revenue guidance",
                company_id="642f5b1abc1234deadbeef00",
                limit=10
            )
        """
        
    

        # 1) Dense embedding of the query
        dense_vec = generate_vector(query_text)

        # 2) Sparse (BM25) embedding of the query
        sparse_dict = splade_sparse(query_text, in_docker=in_docker)
        sparse_vec = rest_models.SparseVector(
            indices=list(sparse_dict.keys()),
            values=list(sparse_dict.values())
        )
        

        must_conditions = [
            FieldCondition(key="company_id", match=MatchValue(value=str(company_id)))
        ]
       
        
        flt = models.Filter(must=must_conditions)

        # 4) Hybrid query: prefetch both sparse & dense legs, then fuse (RRF by default)
        hits = qdrant_client.query_points(
            collection_name=PAGES_COLLECTION_NAME,
            prefetch=[
                # sparse leg
                models.Prefetch(
                    query=sparse_vec,
                    using="sparse",          # name of your sparse vector space
                    limit=50                 # retrieve up to 50 before fusion
                ),
                # dense leg
                models.Prefetch(
                    query=dense_vec,
                    using="dense",           # name of your dense vector space
                    limit=1
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),  # fuse the two legs
            query_filter=flt,
            with_payload=True,
            limit=limit,          # final top-K after fusion
        )
        
        return hits

            
class UploadedDRHP(DynamicDocument):
    processing_status = StringField(required=True, choices=PROCESSING_STATUS_TYPES)
    upload_timestamp = DateTimeField(required=True)
    uploaded_file_url = StringField(required=True)
    company_name = StringField(required=True)
    corporate_identity_number = StringField(required=True)
    failed_reason = StringField()
    retries = IntField(default=0)

    meta = {
        "collection": "uploaded_drhp" 
    }

class CostMap(DynamicDocument):
    copmpany_id = ReferenceField('Company')
    total_input_cost_usd = FloatField(default=0.0)
    total_output_cost_usd = FloatField(default=0.0)
    total_processing_time = FloatField()
    uploaded_by = ReferenceField('User')
    
                
    


if __name__ == "__main__":
    connect(
        db=os.getenv('MONGO_DB'),
        host=os.getenv('MONGO_URI'),
        alias='default'
    )

    hits = Pages.search(
        query_text="find revenue guidance",
        company_id="684184d68dc1408babadf604",
        limit=10
    )
    print("hits", hits)