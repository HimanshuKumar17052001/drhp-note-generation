from app.models.schemas import Company, SebiChecklist, BseChecklist, StandardChecklist, PeopleAndEntities, Pages, UploadedDRHP
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

class CompanyCleaner:
    def __init__(self, failed_reason: str):
        try:
            
            company_upload_document = UploadedDRHP.objects(processing_status="PENDING").order_by("+upload_timestamp").first()
            print("Company found in uploaded documents", company_upload_document)
            self.corporate_identity_number = company_upload_document.corporate_identity_number
            self.failed_reason = failed_reason
            self.clean_company()
            print("Company cleaned")
               
        except Exception as e:
            print("Error in cleaning company document intilizatization", e)
            

    def send_email(self,subject, message, from_addr, to_addrs):
        try:
            msg = MIMEMultipart()
            msg['From'] = from_addr
            msg['To'] = ", ".join(to_addrs)
            msg['Subject'] = subject

            msg.attach(MIMEText(message, 'plain'))

            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(from_addr, os.getenv("EMAIL_PASSWORD"))  
            server.sendmail(from_addr, to_addrs, msg.as_string())
            server.quit()
            print(f"Email sent successfully to {', '.join(to_addrs)}")
        except Exception as e:
            print("Error in sending email:", e)



            
    def clean_company(self):
        try:
            company = Company.objects(corporate_identity_number=self.corporate_identity_number).first()
            UploadedDrhpDocument = UploadedDRHP.objects(corporate_identity_number=self.corporate_identity_number).first()
            
            print("Company found in company collection", company)
            
            if company:
                company_id = company.id
                company.delete()
                SebiChecklist.objects(company_id=company_id).delete()
                BseChecklist.objects(company_id=company_id).delete()
                StandardChecklist.objects(company_id=company_id).delete()
                PeopleAndEntities.objects(company_id=company_id).delete()
                Pages.objects(company=company).delete()
                
                
                if UploadedDrhpDocument.retries < 3:
                    UploadedDrhpDocument.retries += 1
                    UploadedDrhpDocument.failed_reason = self.failed_reason
                    UploadedDrhpDocument.save()
                else:
                    UploadedDrhpDocument.processing_status = "FAILED"
                    UploadedDrhpDocument.save()
                    company_name = company.company_name if company else "Unknown"
                    message = f"Processing of company {company_name} with CIN {self.corporate_identity_number} has failed due to {self.failed_reason}."
                    from_addr = "team@onfinance.in"
                    to_addrs = [email.strip() for email in os.getenv("EMAIL_RECEPIENTS_LIST").split(",")]

                    subject = f"Processing Failed for Company: {company_name}, CIN: {self.corporate_identity_number}"
                    # self.send_email(subject, message, from_addr, to_addrs)
                    
                
            else:
                print("Company not found in company collection marking it as failed")
                
                UploadedDrhpDocument.processing_status = "FAILED"
                UploadedDrhpDocument.save()
                
                message = f"Processing of company with CIN {self.corporate_identity_number} has failed because the company was not found in the company collection."
                from_addr = "team@onfinance.in"
                to_addrs = [email.strip() for email in os.getenv("EMAIL_RECEPIENTS_LIST").split(",")]
                subject = f"Processing Failed for, CIN: {self.corporate_identity_number}"
                # self.send_email(subject, message, from_addr, to_addrs)
              
        except Exception as e:
            print("Error in cleaning company document", e)
            
