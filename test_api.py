#!/usr/bin/env python3
"""
Test script for DRHP API endpoints
"""

import requests
import json
import os
from datetime import datetime

# API base URL
API_BASE_URL = "http://localhost:8000"


def test_health_check():
    """Test health check endpoint"""
    try:
        response = requests.get(f"{API_BASE_URL}/health")
        print(f"Health check: {response.status_code} - {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Health check failed: {e}")
        return False


def test_get_companies():
    """Test getting companies"""
    try:
        response = requests.get(f"{API_BASE_URL}/companies/")
        print(f"Get companies: {response.status_code}")
        if response.status_code == 200:
            companies = response.json()
            print(f"Found {len(companies)} companies:")
            for company in companies:
                print(f"  - {company['name']} (ID: {company['id']})")
                print(f"    CIN: {company['corporate_identity_number']}")
                print(f"    Status: {company['processing_status']}")
                print(f"    Has markdown: {company['has_markdown']}")
                print()
        return response.status_code == 200
    except Exception as e:
        print(f"Get companies failed: {e}")
        return False


def test_get_company_details(company_id):
    """Test getting specific company details"""
    try:
        response = requests.get(f"{API_BASE_URL}/company/{company_id}")
        print(f"Get company details: {response.status_code}")
        if response.status_code == 200:
            company = response.json()
            print(f"Company: {company['name']}")
            print(f"  CIN: {company['corporate_identity_number']}")
            print(f"  Status: {company['processing_status']}")
            print(f"  Has markdown: {company['has_markdown']}")
        return response.status_code == 200
    except Exception as e:
        print(f"Get company details failed: {e}")
        return False


def test_get_company_markdown(company_id):
    """Test getting company markdown"""
    try:
        response = requests.get(f"{API_BASE_URL}/company/{company_id}/markdown")
        print(f"Get company markdown: {response.status_code}")
        if response.status_code == 200:
            markdown_data = response.json()
            print(f"Markdown for: {markdown_data['company_name']}")
            print(f"Generated at: {markdown_data['generated_at']}")
            print(f"Markdown length: {len(markdown_data['markdown'])} characters")
        return response.status_code == 200
    except Exception as e:
        print(f"Get company markdown failed: {e}")
        return False


def test_get_company_report_html(company_id):
    """Test getting company HTML report"""
    try:
        response = requests.get(f"{API_BASE_URL}/company/{company_id}/report-html")
        print(f"Get company HTML report: {response.status_code}")
        if response.status_code == 200:
            report_data = response.json()
            print(f"HTML report for: {report_data['company_name']}")
            print(f"Generated at: {report_data['generated_at']}")
            print(f"HTML length: {len(report_data['html'])} characters")
        return response.status_code == 200
    except Exception as e:
        print(f"Get company HTML report failed: {e}")
        return False


def test_get_company_report_html_companies(company_id):
    """Test getting company HTML report from companies endpoint"""
    try:
        response = requests.get(f"{API_BASE_URL}/companies/{company_id}/report-html")
        print(f"Get company HTML report (companies): {response.status_code}")
        if response.status_code == 200:
            report_data = response.json()
            print(f"HTML report for: {report_data['company_name']}")
            print(f"Generated at: {report_data['generated_at']}")
            print(f"HTML length: {len(report_data['html'])} characters")
        return response.status_code == 200
    except Exception as e:
        print(f"Get company HTML report (companies) failed: {e}")
        return False


def test_get_company_markdown_companies(company_id):
    """Test getting company markdown from companies endpoint"""
    try:
        response = requests.get(f"{API_BASE_URL}/companies/{company_id}/markdown")
        print(f"Get company markdown (companies): {response.status_code}")
        if response.status_code == 200:
            markdown_data = response.json()
            print(f"Markdown for: {markdown_data['company_name']}")
            print(f"Generated at: {markdown_data['generated_at']}")
            print(f"Markdown length: {len(markdown_data['markdown'])} characters")
        return response.status_code == 200
    except Exception as e:
        print(f"Get company markdown (companies) failed: {e}")
        return False


def test_generate_report_pdf():
    """Test PDF generation endpoint"""
    try:
        test_data = {
            "markdown_content": "# Test Report\n\nThis is a test markdown content.",
            "company_name": "Test Company",
        }
        response = requests.post(f"{API_BASE_URL}/generate-report-pdf/", json=test_data)
        print(f"Generate report PDF: {response.status_code}")
        if response.status_code == 200:
            print("PDF generated successfully")
        return response.status_code == 200
    except Exception as e:
        print(f"Generate report PDF failed: {e}")
        return False


def test_debug_companies():
    """Test debug companies endpoint"""
    try:
        response = requests.get(f"{API_BASE_URL}/debug/companies")
        print(f"Debug companies: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Total companies: {data['total_companies']}")
            print(f"Total markdown docs: {data['total_markdown_docs']}")
            if data["companies"]:
                print("Companies:")
                for company in data["companies"]:
                    print(
                        f"  - {company['name']} (ID: {company['id']}, Has markdown: {company['has_markdown']})"
                    )
        return response.status_code == 200
    except Exception as e:
        print(f"Debug companies failed: {e}")
        return False


def test_get_final_report(company_id):
    """Test get final report endpoint with different formats"""
    try:
        # Test markdown format
        response = requests.get(f"{API_BASE_URL}/report/{company_id}?format=markdown")
        print(f"Get final report (markdown): {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"  Company: {data['company_name']}")
            print(f"  Format: {data['format']}")
            print(f"  Content length: {len(data['content'])} characters")

        # Test HTML format
        response = requests.get(f"{API_BASE_URL}/report/{company_id}?format=html")
        print(f"Get final report (html): {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"  Company: {data['company_name']}")
            print(f"  Format: {data['format']}")
            print(f"  Content length: {len(data['content'])} characters")

        # Test PDF format
        response = requests.get(f"{API_BASE_URL}/report/{company_id}?format=pdf")
        print(f"Get final report (pdf): {response.status_code}")
        if response.status_code == 200:
            print("  PDF generated successfully")

        return True
    except Exception as e:
        print(f"Get final report failed: {e}")
        return False


def test_get_company_status(company_id):
    """Test getting company processing status"""
    try:
        response = requests.get(f"{API_BASE_URL}/company/{company_id}/status")
        print(f"Get company status: {response.status_code}")
        if response.status_code == 200:
            status = response.json()
            print(f"Status: {status['overall_status']}")
            print(f"  Pages done: {status['pages_done']}")
            print(f"  Qdrant done: {status['qdrant_done']}")
            print(f"  Checklist done: {status['checklist_done']}")
            print(f"  Markdown done: {status['markdown_done']}")
        return response.status_code == 200
    except Exception as e:
        print(f"Get company status failed: {e}")
        return False


def main():
    """Run all tests"""
    print("Testing DRHP API endpoints...")
    print("=" * 50)

    # Test health check
    if not test_health_check():
        print("❌ Health check failed - API may not be running")
        return

    print("✅ Health check passed")
    print()

    # Test getting companies
    if not test_get_companies():
        print("❌ Get companies failed")
        return

    print("✅ Get companies passed")
    print()

    # Test debug endpoint
    test_debug_companies()
    print()

    # If we have companies, test individual company endpoints
    try:
        response = requests.get(f"{API_BASE_URL}/companies/")
        if response.status_code == 200:
            companies = response.json()
            if companies:
                # Test with first company
                company_id = companies[0]["id"]
                print(
                    f"Testing with company: {companies[0]['name']} (ID: {company_id})"
                )
                print()

                # Test company details
                test_get_company_details(company_id)
                print()

                # Test company status
                test_get_company_status(company_id)
                print()

                # Test company markdown (only if company has markdown)
                if companies[0]["has_markdown"]:
                    test_get_company_markdown(company_id)
                    print()
                    test_get_company_report_html(company_id)
                    print()
                    test_get_company_report_html_companies(company_id)
                    print()
                    test_get_company_markdown_companies(company_id)
                    print()
                    test_get_final_report(company_id)
                else:
                    print("Company doesn't have markdown yet")

                # Test PDF generation
                print()
                test_generate_report_pdf()

                print("✅ All tests completed")
            else:
                print("No companies found in database")
        else:
            print("Failed to get companies for testing")
    except Exception as e:
        print(f"Error during testing: {e}")


if __name__ == "__main__":
    main()
