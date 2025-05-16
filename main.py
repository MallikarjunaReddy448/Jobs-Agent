#!/usr/bin/env python
# 📁 Path: auto_job_applier/main.py

"""
Main application for Auto Job Applier.
This script integrates all modules and provides a complete workflow for:
1. Resume parsing
2. Profile management
3. Job searching
4. Job matching/ranking
5. Job application
"""

import os
import sys
import time
import json
import random
import argparse
import logging
# from industry_selection_prevent_apply import select_multiple_industries
# from industry_selection_improved import select_multiple_industries
# from industry_selection_refresh_aware import select_multiple_industries
# from industry_selection_visual_based import select_multiple_industries
# from industry_selection_reload_based  import select_multiple_industries
# from industry_selection_scroll_based import select_multiple_industries
# from industry_selection_last_fix import select_multiple_industries #latest final version
from industry_selection_verify_new import select_multiple_industries
from department_selection_verify import select_multiple_departments
from pathlib import Path
from datetime import datetime, date

# Define global variable for database availability
DATABASE_AVAILABLE = False

# Import database integration module
try:
    from database.db_integration_main import (
        check_database_connection, get_user_by_email, save_user_data,
        save_user_skills, get_user_skills, save_job_listings,
        get_jobs_for_application, update_job_status, save_job_application,
        get_application_stats, get_recent_jobs, save_search_preferences,
        get_search_preferences, save_user_certification, get_user_certifications,
        get_certification_by_name, update_user_resume
    )
    DATABASE_AVAILABLE = True
    print("Database integration module loaded successfully")
except ImportError as e:
    print(f"Warning: Database integration module not available: {e}")
    print("Using file-based storage instead")

# Try to import inquirer, but don't fail if it's not available
try:
    import inquirer
    has_inquirer = True
except ImportError:
    has_inquirer = False
    print("Warning: inquirer module not found. Using standard input instead.")
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from concurrent.futures import ThreadPoolExecutor


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('auto_job_applier.log')
    ]
)

logger = logging.getLogger('AutoJobApplier')

# Add the project directory to the path
current_dir = Path(__file__).parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

# Import modules
try:
    # Resume parsing and integrated search
    from stages.resume_parser.resume_parser import extract_resume_text, extract_skills, clean_skills, deduplicate_skills, selected_search_skills
    from stages.integrated_search.integrated_search import integrated_search_pipeline

    # Profile management
    from stages.job_applier.user_profile_manager import UserProfileManager

    # User data collection
    from stages.user_data.user_data_collector import collect_user_data

    # Job search
    from stages.job_search.job_search_enhanced import run_job_search

    # Naukri handler
    from stages.browser_automation.portal_handlers.naukri_handler import NaukriHandler
    from stages.browser_automation.smart_automation import SmartAutomationHandler

    # Naukri job extractor
    from stages.job_applier.naukri_job_extractor import extract_job_details_from_url

    # Job matching
    # We'll import specific functions based on the user's choice

    # Job application
    from stages.job_applier.job_applier import JobApplier

    # Import functions from test_apply_button.py and test_chatbot_form.py
    try:
        from test_apply_button import test_apply_button_click
        logger.info("Successfully imported test_apply_button_click function")
    except ImportError as e:
        logger.error(f"Error importing test_apply_button_click: {e}")
        test_apply_button_click = None

    try:
        from test_chatbot_form import fill_chatbot_form
        logger.info("Successfully imported fill_chatbot_form function")
    except ImportError as e:
        logger.error(f"Error importing fill_chatbot_form: {e}")
        fill_chatbot_form = None

    # Import the Naukri chatbot test function
    try:
        from test_naukri_chatbot import test_naukri_chatbot
        logger.info("Successfully imported test_naukri_chatbot function")
    except ImportError as e:
        logger.error(f"Error importing test_naukri_chatbot: {e}")
        test_naukri_chatbot = None

    # Import any other necessary modules
    try:
        from stages.job_filter.job_filter import filter_and_rank_jobs
    except ImportError:
        print("Warning: job_filter module not found. Some functionality may be limited.")

    # All modules imported successfully
    logger.info("All modules imported successfully")

except ImportError as e:
    logger.error(f"Error importing modules: {e}")
    print(f"Error: {e}")
    print("Please make sure all required modules are installed and in the correct locations.")
    sys.exit(1)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Auto Job Applier')

    # General arguments
    parser.add_argument('--resume', help='Path to resume file (PDF or DOCX)')
    parser.add_argument('--email', help='User email address for profile management')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--output', help='Output directory for results', default='results')

    # Job search arguments
    parser.add_argument('--roles', help='Job roles to search for (comma-separated)')
    parser.add_argument('--locations', help='Job locations to search in (comma-separated)')
    parser.add_argument('--skills', help='Skills to include in search (comma-separated)')
    parser.add_argument('--freshness', choices=['1', '3', '7', '15', '30'], help='Job freshness filter in days')

    # Job matching arguments
    parser.add_argument('--min-score', type=float, default=7.0, help='Minimum match score to apply (0-10)')
    parser.add_argument('--max-jobs', type=int, default=60, help='Maximum number of jobs to process')

    # Job application arguments
    parser.add_argument('--apply', action='store_true', help='Actually apply to jobs (otherwise just simulate)')
    parser.add_argument('--auto-apply', action='store_true', help='Automatically apply to all eligible jobs without manual selection')
    parser.add_argument('--portal', choices=['naukri', 'linkedin'], default='naukri', help='Job portal to use')

    # Mode selection
    parser.add_argument('--mode', choices=['full', 'parse', 'search', 'match', 'apply'], default='full',
                      help='Mode to run in (default: full workflow)')

    return parser.parse_args()

def ensure_directory(directory):
    """Ensure a directory exists."""
    os.makedirs(directory, exist_ok=True)
    return directory

def save_json(data, filename):
    """Save data to a JSON file.

    Note: This function is kept for backward compatibility and debugging purposes.
    In production, data should be stored in the database.
    """
    if not DATABASE_AVAILABLE:
        # Only save to file if database is not available
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Data saved to {filename}")
    else:
        logger.debug(f"Skipping file save to {filename} - using database instead")

def load_json(filename):
    """Load data from a JSON file.

    Note: This function is kept for backward compatibility and debugging purposes.
    In production, data should be retrieved from the database.
    """
    if not DATABASE_AVAILABLE:
        # Only load from file if database is not available
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Error loading {filename}: {e}")
            return None
    else:
        logger.debug(f"Skipping file load from {filename} - using database instead")
        return None


def apply_to_multiple_jobs(job_queue, chrome_profile_path, user_data, output_dir):
    """
    Apply to multiple jobs using test_naukri_chatbot.py.

    Args:
        job_queue: List of job dictionaries with URLs and details
        chrome_profile_path: Path to Chrome profile
        user_data: User data dictionary
        output_dir: Directory to save results

    Returns:
        Dictionary with results for each job
    """
    logger.info(f"Applying to {len(job_queue)} jobs using test_naukri_chatbot.py")

    # Save job queue to a temporary file (needed for subprocess)
    job_queue_file = os.path.join(output_dir, "job_queue.json")
    with open(job_queue_file, 'w', encoding='utf-8') as f:
        json.dump(job_queue, f, indent=2, ensure_ascii=False)
    logger.info(f"Temporary job queue saved to {job_queue_file}")

    # Save user data to a temporary file (needed for subprocess)
    user_data_file = os.path.join(output_dir, "temp_user_data.json")
    with open(user_data_file, 'w', encoding='utf-8') as f:
        json.dump(user_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Temporary user data saved to {user_data_file}")

    # Construct the command to run test_naukri_chatbot.py as a separate process
    cmd = [
        sys.executable,  # Python executable
        os.path.join(current_dir, "test_naukri_chatbot.py"),
        job_queue_file
    ]

    # Run the command and capture the output
    import subprocess
    process = subprocess.run(cmd, capture_output=True, text=True)

    # Print the output
    print(process.stdout)

    # Check if the process was successful
    success = process.returncode == 0

    if success:
        logger.info("Successfully applied to jobs using test_naukri_chatbot.py")
    else:
        logger.error(f"Error applying to jobs: {process.stderr}")

    # Try to load the application results
    results_file = os.path.join(output_dir, "application_results.json")
    results = load_json(results_file)

    # If results couldn't be loaded or is not a list, return the original job queue with applied=False
    if not results or not isinstance(results, list):
        logger.warning("Could not load application results. Using original job queue with applied=False")
        # Mark all jobs as not applied
        for job in job_queue:
            job["applied"] = False
        return job_queue

    return results


# Import the job eligibility function from keyword_matcher.py
from stages.llm_matcher.keyword_matcher import check_job_eligibility, get_matching_skills

def search_naukri_with_selenium(profile_path, roles, locations, experience, freshness, max_jobs=10, industries=None, departments=None):
    """Search for jobs on Naukri.com using Selenium.

    Args:
        profile_path: Path to Chrome profile
        roles: List of job roles to search for
        locations: List of locations to search in
        experience: Minimum experience (e.g., "2")
        freshness: Job freshness filter (e.g., "3" for 3 days)
        max_jobs: Maximum number of jobs to extract

    Returns:
        List of job links
    """
    # Create screenshots directory
    screenshots_dir = ensure_directory(os.path.join(current_dir, "screenshots"))

    # Create a search query from roles
    search_query = ", ".join(roles)

    # Create a location query from locations
    location_query = ", ".join(locations)

    # Set up Chrome options
    options = Options()
    options.add_argument(f"user-data-dir={profile_path}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Initialize Chrome
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()

    # Create a WebDriverWait instance
    wait = WebDriverWait(driver, 10)

    try:
        # Navigate to Naukri.com
        print("\n🌐 Navigating to Naukri.com")
        driver.get("https://www.naukri.com")

        # Take a screenshot
        screenshot_path = os.path.join(screenshots_dir, f"naukri_homepage_{int(time.time())}.png")
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")

        # Wait for page to load
        time.sleep(5)

        # Click on the search container or placeholder
        print("\n🔍 Clicking on search container")

        try:
            # Try to click on the search placeholder
            placeholders = driver.find_elements(By.XPATH, "//span[contains(@class, 'nI-gNb-sb__placeholder')]")
            if placeholders:
                placeholders[0].click()
                print("✅ Clicked on search placeholder")
                time.sleep(2)
            else:
                # Try to click on the search container
                containers = driver.find_elements(By.XPATH, "//div[contains(@class, 'nI-gNb-sb__main')]")
                if containers:
                    containers[0].click()
                    print("✅ Clicked on search container")
                    time.sleep(2)
                else:
                    print("❌ Could not find search container or placeholder")
        except Exception as e:
            print(f"Error clicking search container: {e}")

        # Take a screenshot after clicking
        screenshot_path = os.path.join(screenshots_dir, f"naukri_after_click_{int(time.time())}.png")
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")

        # Enter search query
        print(f"\n🔍 Entering search query: {search_query}")

        try:
            # Try to find and fill the search input using XPath
            search_inputs = driver.find_elements(By.XPATH, "//input[contains(@placeholder, 'keyword') or contains(@placeholder, 'skill') or contains(@placeholder, 'designation')]")
            if search_inputs:
                search_input = search_inputs[0]
                search_input.clear()
                search_input.send_keys(search_query)
                print(f"✅ Filled search input with: {search_query}")
                time.sleep(2)
            else:
                # Try using active element
                active_element = driver.switch_to.active_element
                active_element.clear()
                active_element.send_keys(search_query)
                print(f"✅ Filled search input with active element: {search_query}")
                time.sleep(2)
        except Exception as e:
            print(f"Error filling search input: {e}")

        # Click on experience dropdown using exact XPath
        print("\n🔍 Clicking on experience dropdown")

        try:
            # Use the exact XPath provided
            exp_dropdown_xpath = "/html/body/div[3]/div[2]/div[1]/div/div/div[4]"
            exp_dropdown = driver.find_element(By.XPATH, exp_dropdown_xpath)
            exp_dropdown.click()
            print("✅ Clicked experience dropdown using exact XPath")
            time.sleep(2)

            # Take a screenshot after clicking experience dropdown
            screenshot_path = os.path.join(screenshots_dir, f"naukri_exp_dropdown_{int(time.time())}.png")
            driver.save_screenshot(screenshot_path)
            print(f"Screenshot saved to {screenshot_path}")

            # Use the exact XPath for the dropdown list
            dropdown_list_xpath = "//*[@id='sa-dd-scrollexperienceDD']/div[1]/ul"

            try:
                # Wait for the dropdown list to be visible
                dropdown_list = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, dropdown_list_xpath))
                )

                # Map experience to the appropriate option index
                exp_value = int(experience)
                option_index = 0  # Default to Fresher

                if exp_value == 0:
                    option_index = 1  # Fresher (less than 1 year)
                else:
                    option_index = exp_value + 1  # 1 year = index 2, 2 years = index 3, etc.

                # Limit to 5 years (based on the screenshot)
                if option_index > 6:
                    option_index = 6  # Max 5 years

                # Try to click the specific option by index
                option_xpath = f"{dropdown_list_xpath}/li[{option_index}]"
                option_element = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, option_xpath))
                )

                # Click the option
                option_element.click()
                print(f"✅ Selected experience option at index {option_index}")
                time.sleep(2)

            except Exception as e:
                print(f"Error selecting experience with exact XPath: {e}")
        except Exception as e:
            print(f"Error clicking experience dropdown: {e}")

        # Enter location
        print(f"\n🔍 Entering location: {location_query}")

        try:
            # Try to find and fill the location input using XPath
            location_inputs = driver.find_elements(By.XPATH, "//input[contains(@placeholder, 'location')]")
            if location_inputs:
                location_input = location_inputs[0]
                location_input.clear()
                location_input.send_keys(location_query)
                print(f"✅ Filled location input with: {location_query}")
                time.sleep(2)
            else:
                # Try using active element
                active_element = driver.switch_to.active_element
                active_element.clear()
                active_element.send_keys(location_query)
                print(f"✅ Filled location input with active element: {location_query}")
                time.sleep(2)
        except Exception as e:
            print(f"Error filling location input: {e}")

        # Click search button
        print("\n🔍 Clicking search button")

        try:
            # Try to find and click the search button
            search_buttons = driver.find_elements(By.XPATH, "//button[contains(@class, 'nI-gNb-sb__icon-wrapper')]")
            if search_buttons:
                search_buttons[0].click()
                print("✅ Clicked search button")
                time.sleep(2)
            else:
                # Try pressing Enter on the active element
                active_element = driver.switch_to.active_element
                active_element.send_keys(Keys.ENTER)
                print("✅ Pressed Enter key to search")
                time.sleep(2)
        except Exception as e:
            print(f"Error clicking search button: {e}")

        # Wait for search results to load
        print("\n⏳ Waiting for search results to load...")
        time.sleep(8)

        # Take a screenshot of search results
        screenshot_path = os.path.join(screenshots_dir, f"naukri_results_{int(time.time())}.png")
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")

        # Apply job freshness filter
        if freshness:
            print("\n🔍 Applying job freshness filter")

            try:
                # Use the exact XPath provided
                freshness_filter_xpath = "/html/body/div/div/main/div[1]/div[1]/div/div/div[2]/div[11]"

                # Wait for the filter to be clickable
                freshness_filter = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, freshness_filter_xpath))
                )

                # Click the filter
                freshness_filter.click()
                print("✅ Clicked job freshness filter")
                time.sleep(2)

                # Map freshness to option index
                freshness_map = {
                    "1": 1,  # Last 1 day
                    "3": 2,  # Last 3 days
                    "7": 3,  # Last 7 days
                    "15": 4,  # Last 15 days
                    "30": 5   # Last 30 days
                }

                option_index = freshness_map.get(freshness, 5)  # Default to 30 days

                # Use the exact XPath for the dropdown list
                dropdown_list_xpath = "/html/body/div/div/main/div[1]/div[1]/div/div/div[2]/div[11]/div[2]/div/div/ul"

                try:
                    # Wait for the dropdown list to be visible
                    dropdown_list = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, dropdown_list_xpath))
                    )

                    # Try to click the specific option by index
                    option_xpath = f"{dropdown_list_xpath}/li[{option_index}]"
                    option_element = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, option_xpath))
                    )

                    # Click the option
                    option_element.click()
                    print(f"✅ Selected job freshness option at index {option_index}")
                    time.sleep(5)  # Wait for results to update

                except Exception as e:
                    print(f"Error selecting job freshness option with exact XPath: {e}")

                    # Try using JavaScript to select the option
                    try:
                        day_text = ["Last 1 day", "Last 3 days", "Last 7 days", "Last 15 days", "Last 30 days"][option_index - 1]
                        script = f"""
                            (function() {{
                                var allLis = document.querySelectorAll('li');
                                for (var i = 0; i < allLis.length; i++) {{
                                    var li = allLis[i];
                                    if (li.textContent.includes("{day_text}")) {{
                                        li.click();
                                        return true;
                                    }}
                                }}
                                return false;
                            }})();
                        """

                        js_result = driver.execute_script(script)
                        if js_result:
                            print(f"✅ Selected job freshness option '{day_text}' using JavaScript")
                            time.sleep(5)  # Wait for results to update
                        else:
                            print(f"❌ Could not find option with text '{day_text}'")
                    except Exception as e:
                        print(f"Error with JavaScript approach: {e}")
            except Exception as e:
                print(f"Error applying job freshness filter: {e}")

        # Industry Type Filter
        print("\n🏢 Do you want to filter by Industry Type?")
        apply_industry_filter = input("Apply Industry Type filter? (y/n): ").strip().lower() == 'y'

        if apply_industry_filter:
            # Define industry types available on Naukri
            


            # # Display industry types
            # print("\nAvailable Industry Types:")
            # for i, industry in enumerate(industries, 1):
            #     print(f"{i}. {industry}")

            # # Allow multiple selections
            # selected_industries = []
            # while True:
            #     industry_input = input("\nEnter industry number (or 0 to finish selection): ").strip()
            #     if industry_input == "0":
            #         break

            #     if industry_input.isdigit() and 1 <= int(industry_input) <= len(industries):
            #         selected_index = int(industry_input) - 1
            #         selected_industry = industries[selected_index]
            #         if selected_industry not in selected_industries:
            #             # Add the selected industry if not already in list
            #             selected_industries.append(selected_industry)
            #             print(f"✅ Added {selected_industry}")
            #             print(f"Current selections: {', '.join(selected_industries)}")
            #         else:
            #             print(f"⚠️ {selected_industry} already selected")
            #     else:
            #         print(f"⚠️ Please enter a valid number between 1 and {len(industries)}, or 0 to finish")
            selected_industries = industries
            if selected_industries:
                print(f"\n🏢 Selected Industries: {', '.join(selected_industries)}")
                
                # # Try to find and click the "View more" button for industries first
                # try:
                #     # Try multiple selectors for the industry "View more" button
                #     view_more_selectors = [
                #         "//*[@id='industryIdGid']/span",  # Specific industry view more xpath
                #         '//*[@id="industryTypeIdGid"]/span',
                #         "/html/body/div/div/main/div[1]/div[1]/div/div/div[2]/div[10]/div[2]/a/span",
                #         "//span[contains(text(),'View More')]",
                #         "//span[contains(text(),'View More')])[7]",
                #         "//div[contains(@class, 'industry-filter')]//span[contains(text(), 'View more')]",
                #         "//div[contains(@class, 'industry-filter')]//span[contains(@class, 'view-more')]",
                #         "//div[contains(@class, 'styles_view-more')]",
                #         "//span[contains(text(), 'View more')]"
                #     ]

                #     view_more_clicked = False
                #     for selector in view_more_selectors:
                #         try:
                #             view_more_button = WebDriverWait(driver, 3).until(
                #                 EC.element_to_be_clickable((By.XPATH, selector))
                #             )
                #             if view_more_button:
                #                 view_more_button.click()
                #                 print("✅ Clicked on 'View more' button for industries")
                #                 time.sleep(2)  # Wait for the full list to appear
                #                 view_more_clicked = True
                #                 break
                #         except:
                #             continue

                #     if not view_more_clicked:
                #         print("⚠️ Could not find 'View more' button for industries, trying alternative approach")
                #         # Click on Industry filter first
                #         industry_filter_selectors = [
                #             "//div[contains(@class, 'industry-filter')]",
                #             "//div[contains(text(), 'Industry')]/parent::div",
                #             "//span[contains(text(), 'Industry')]/parent::div"
                #         ]

                #         for selector in industry_filter_selectors:
                #             try:
                #                 industry_filter = WebDriverWait(driver, 3).until(
                #                     EC.element_to_be_clickable((By.XPATH, selector))
                #                 )
                #                 if industry_filter:
                #                     industry_filter.click()
                #                     print("✅ Clicked on Industry filter")
                #                     time.sleep(1)
                #                     break
                #             except:
                #                 continue

                # except Exception as e:
                #     print(f"❌ Error with View more button: {e}")



                try:
                    # Use the imported industry selection function
                    print(f"🏢 Using imported industry selection for: {', '.join(selected_industries)}")
                    select_multiple_industries(driver, selected_industries)
                except Exception as e:
                    print(f"❌ Error with industry selection: {e}")
                
                # Click outside any open popups to close them
                try:
                    print("\n🔍 Closing any open filter popups...")
                    # Try clicking on the body element to close any open popups
                    driver.execute_script("document.body.click();")
                    time.sleep(2)

                    # If that doesn't work, try clicking at a random position away from popups
                    actions = ActionChains(driver)
                    actions.move_by_offset(100, 100).click().perform()
                    time.sleep(2)
                    
                    # Reset the mouse position
                    actions.move_by_offset(-100, -100).perform()
                    print("✅ Clicked outside popups")                  
                except Exception as e:
                    print(f"⚠️ Error closing popups: {e}")
                
                

        # Department/Functional Area Filter
        print("\n🧩 Do you want to filter by Department/Functional Area?")
        apply_department_filter = input("Apply Department filter? (y/n): ").strip().lower() == 'y'

        if apply_department_filter:
            


            # Display departments
            print("\nAvailable Departments/Functional Areas:")
            for i, department in enumerate(departments, 1):
                print(f"{i}. {department}")

            # Allow multiple selections
            selected_departments = []
            while True:
                department_input = input("\nEnter department number (or 0 to finish selection): ").strip()
                if department_input == "0":
                    break

                if department_input.isdigit() and 1 <= int(department_input) <= len(departments):
                    selected_index = int(department_input) - 1
                    selected_department = departments[selected_index]
                    if selected_department not in selected_departments:
                        selected_departments.append(selected_department)
                        print(f"✅ Added: {selected_department}")
                    else:
                        print(f"⚠️ {selected_department} already selected")
                else:
                    print(f"Please enter a valid number between 1 and {len(departments)}, or 0 to finish")

            if selected_departments:
                # print(f"\n🧩 Selected Departments: {', '.join(selected_departments)}")
                try:
                    # Use the imported industry selection function
                    print(f"🏢 Using imported department selection for: {', '.join(selected_departments)}")
                    select_multiple_departments(driver, selected_departments)
                except Exception as e:
                    print(f"❌ Error with department selection: {e}")
                

        # Wait for results to update
        print("\n⏳ Waiting for results to update...")
        time.sleep(50000000)

        # Take a screenshot of final results
        screenshot_path = os.path.join(screenshots_dir, f"naukri_final_results_{int(time.time())}.png")
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")

        # Extract job links from multiple pages (pages 1-3)
        print("\n🔍 Extracting job links from pages 1-3")

        # Initialize list to store job links
        job_links = []
        current_page = 1
        max_pages = 3  # Extract jobs up to page 3

        # We're already on page 1, so no need to navigate
        print(f"\n🔍 Starting from page {current_page}")

        # Take a screenshot of the first page
        screenshot_path = os.path.join(screenshots_dir, f"naukri_page_{current_page}_{int(time.time())}.png")
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")

        # Now extract job links from pages 4-7
        while current_page <= max_pages:
            print(f"\n🔍 Processing page {current_page} of {max_pages}")

            # Try different job card selectors
            job_cards_selectors = [
                "//div[contains(@class, 'jobTupleHeader')]/parent::*",  # New Naukri layout
                "//article[contains(@class, 'jobTuple')]",              # Old Naukri layout
                "//div[contains(@class, 'job-tuple')]",                 # Alternative selector
                "//div[contains(@class, 'srp-tuple')]",                 # Another alternative
                "//div[contains(@class, 'list-container')]/div"          # Generic container
            ]

            job_cards = []
            for selector in job_cards_selectors:
                try:
                    # Wait for elements with this selector
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, selector))
                    )

                    # Find all elements with this selector
                    cards = driver.find_elements(By.XPATH, selector)
                    if cards and len(cards) > 0:
                        job_cards = cards
                        print(f"Found {len(job_cards)} job cards on page {current_page} using selector: {selector}")
                        break
                except:
                    continue

            if not job_cards:
                print(f"Could not find job cards on page {current_page} with any selector")
                break  # Exit the loop if no job cards found

            # Extract links from job cards on this page
            page_job_links = []
            for i, card in enumerate(job_cards, 1):
                try:
                    # Job Title - try multiple selectors
                    title_selectors = [
                        ".//a[@class='title ellipsis']",
                        ".//a[contains(@class, 'title')]",
                        ".//a[contains(@class, 'jobTitle')]",
                        ".//div[contains(@class, 'title')]/a",
                        ".//div[contains(@class, 'jobTitle')]/a"
                    ]

                    for selector in title_selectors:
                        try:
                            title_element = card.find_element(By.XPATH, selector)
                            job_url = title_element.get_attribute("href")
                            if job_url:
                                page_job_links.append(job_url)
                                print(f"  ✅ Extracted job link {i} on page {current_page}: {job_url}")
                                break
                        except:
                            continue
                except Exception as e:
                    print(f"  ❌ Error extracting job link {i} on page {current_page}: {e}")

            # Add job links from this page to the main list
            job_links.extend(page_job_links)
            print(f"\n✅ Extracted {len(page_job_links)} job links from page {current_page}")

            # Check if we've reached the maximum number of jobs
            if len(job_links) >= max_jobs:
                print(f"Reached maximum number of jobs ({max_jobs}). Stopping pagination.")
                job_links = job_links[:max_jobs]  # Trim to max_jobs
                break

            # Move to the next page if we haven't reached the maximum pages
            if current_page < max_pages:
                try:
                    # Try multiple selectors for the Next button
                    next_button_selectors = [
                        "/html/body/div/div/main/div[1]/div[2]/div[3]/div/a[2]",  # Full XPath
                        "//a[contains(@class, 'styles_btn-secondary') and contains(., 'Next')]",  # Class and text
                        "//a[contains(., 'Next')]/i[contains(@class, 'arrow')]/parent::a",  # Text and icon
                        "//a[contains(@href, 'jobs') and contains(., 'Next')]",  # URL and text
                        "#lastCompMark > a:nth-child(4)"  # CSS selector
                    ]

                    next_button = None
                    for selector in next_button_selectors:
                        try:
                            if selector.startswith("#"):
                                # CSS selector
                                next_button = driver.find_element(By.CSS_SELECTOR, selector)
                            else:
                                # XPath
                                next_button = driver.find_element(By.XPATH, selector)

                            if next_button and next_button.is_displayed() and next_button.is_enabled():
                                print(f"\n🔍 Found Next button using selector: {selector}")
                                break
                        except:
                            continue

                    if next_button:
                        # Take a screenshot before clicking Next
                        screenshot_path = os.path.join(screenshots_dir, f"naukri_before_next_{current_page}_{int(time.time())}.png")
                        driver.save_screenshot(screenshot_path)

                        # Click the Next button
                        next_button.click()
                        print(f"\n🔍 Clicked Next button to navigate to page {current_page + 1}")

                        # Wait for the next page to load
                        time.sleep(5)

                        # Take a screenshot after clicking Next
                        screenshot_path = os.path.join(screenshots_dir, f"naukri_after_next_{current_page + 1}_{int(time.time())}.png")
                        driver.save_screenshot(screenshot_path)

                        current_page += 1
                    else:
                        print("\n❌ Could not find Next button. This might be the last page.")
                        break
                except Exception as e:
                    print(f"\n❌ Error navigating to next page: {e}")
                    break
            else:
                # We've reached the maximum number of pages
                break

        print(f"\n✅ Total extracted job links: {len(job_links)}")
        return job_links

    finally:
        # Close browser
        try:
            driver.quit()
            print("\n🔍 Browser closed")
        except:
            pass

        return job_links

def main():
    """Main function."""
    # Access the global variable
    global DATABASE_AVAILABLE

    # Parse arguments
    args = parse_arguments()

    # Create output directory
    output_dir = ensure_directory(args.output)
    logger.info(f"Output directory: {output_dir}")

    # Check database connection if available
    if DATABASE_AVAILABLE:
        logger.info("Checking database connection...")
        if check_database_connection():
            logger.info("Database connection successful")
            print("✅ Database connection successful")
        else:
            logger.error("Database connection failed")
            print("❌ Database connection failed. Using file-based storage instead.")
            # Update the global variable
            DATABASE_AVAILABLE = False

    # Initialize user profile manager
    user_manager = UserProfileManager()

    # Collect user data
    print("\n📋 Collecting user data for job applications...")

    # Check if user exists in database
    user_id = None
    if DATABASE_AVAILABLE and args.email:
        user = get_user_by_email(args.email)
        if user:
            logger.info(f"User found in database: {args.email}")
            print(f"✅ User found in database: {args.email}")
            user_id = user['user_id']

            # Convert database user data to a dictionary for validation
            user_data = {}
            for key, value in user.items():
                if key not in ['user_id', 'display_id', 'created_at', 'updated_at', 'last_login', 'is_active']:
                    user_data[key] = value

            # Import the validate_user_data function from user_data_collector
            from stages.user_data.user_data_collector import validate_user_data

            # Validate user data to ensure all mandatory fields are filled
            is_valid, missing_fields = validate_user_data(user_data)

            if not is_valid:
                logger.info(f"User data is missing mandatory fields: {missing_fields}")
                print(f"\n⚠️ Your profile is missing some mandatory information required for job applications.")
                print(f"Missing fields: {', '.join([field.replace('_', ' ').title() for field in missing_fields])}")
                print("Please provide the following missing information:")

                # Collect missing fields
                for field in missing_fields:
                    if field == "date_of_birth":
                        # Collect date of birth
                        import re
                        dob_pattern = re.compile(r'^\d{1,2}/\d{1,2}/\d{4}$')
                        while True:
                            dob = input("Date of Birth (DD/MM/YYYY): ").strip()
                            if dob and dob_pattern.match(dob):
                                user_data["date_of_birth"] = dob
                                break
                            else:
                                print("Valid date of birth is required in DD/MM/YYYY format.")

                    elif field == "age":
                        # Collect age
                        while True:
                            age = input("Age (in years): ").strip()
                            if age and age.isdigit():
                                user_data["age"] = age
                                break
                            else:
                                print("Age is required and must be a number. Please enter a valid age.")

                    elif field == "gender":
                        # Collect gender
                        while True:
                            gender = input("Gender (Male/Female/Other): ").strip().capitalize()
                            if gender in ["Male", "Female", "Other"]:
                                user_data["gender"] = gender
                                break
                            else:
                                print("Please enter a valid gender (Male, Female, or Other).")

                    elif field == "highest_education":
                        # Collect highest education
                        print("\nEducation Details:")
                        education_options = [
                            "High School", "Diploma", "Bachelor's Degree", "Master's Degree",
                            "PhD", "Professional Degree", "Other"
                        ]
                        print("Highest Education Options:")
                        for i, option in enumerate(education_options, 1):
                            print(f"{i}. {option}")

                        while True:
                            education_input = input("Enter the number for your highest education: ").strip()
                            if education_input.isdigit() and 1 <= int(education_input) <= len(education_options):
                                user_data["highest_education"] = education_options[int(education_input) - 1]
                                break
                            else:
                                print(f"Please enter a valid number between 1 and {len(education_options)}.")

                    elif field == "education_specialization":
                        # Collect education specialization
                        while True:
                            specialization = input("Education Specialization (e.g., Computer Science, Business Administration): ").strip()
                            if specialization:
                                user_data["education_specialization"] = specialization
                                break
                            else:
                                print("Education specialization is required. Please enter your specialization.")

                    else:
                        # Collect other missing fields
                        while True:
                            value = input(f"{field.replace('_', ' ').title()}: ").strip()
                            if value:
                                user_data[field] = value
                                break
                            else:
                                print(f"{field.replace('_', ' ').title()} is required. Please provide this information.")

                print("\n✅ Thank you for providing the missing information.")

                # Update user data in database
                if DATABASE_AVAILABLE:
                    # Save user data to database
                    save_user_data(user_data)
                    logger.info(f"Updated user data in database for ID: {user_id}")
                    print(f"✅ Updated user data in database")

                # User data validation completed
                logger.info("User data validation completed")
                print("\n✅ User data validation completed")
        else:
            logger.info(f"User not found in database: {args.email}")
            print(f"⚠️ User not found in database: {args.email}")
            # Collect user data
            user_data = collect_user_data(resume_path=args.resume, email=args.email)

            if user_data and DATABASE_AVAILABLE:
                # Save user data to database
                user_id = save_user_data(user_data)
                if user_id:
                    logger.info(f"User data saved to database with ID: {user_id}")
                    print(f"✅ User data saved to database with ID: {user_id}")

                    # New user data saved successfully
                    logger.info("New user data saved successfully")
                    print("\n✅ New user data saved successfully")
                else:
                    logger.error("Failed to save user data to database")
                    print("❌ Failed to save user data to database")
    else:
        # Collect user data
        user_data = collect_user_data(resume_path=args.resume, email=args.email)

        if user_data and DATABASE_AVAILABLE:
            # Save user data to database
            user_id = save_user_data(user_data)
            if user_id:
                logger.info(f"User data saved to database with ID: {user_id}")
                print(f"✅ User data saved to database with ID: {user_id}")
            else:
                logger.error("Failed to save user data to database")
                print("❌ Failed to save user data to database")

    # Get user email from collected data
    email = user_data.get("email")
    if not email:
        email = input("Please enter your email address: ").strip()
        user_data["email"] = email

        # Update user data in database if available
        if DATABASE_AVAILABLE and user_id:
            save_user_data(user_data)

    # Save to file only if database is not available
    if not DATABASE_AVAILABLE:
        user_data_file = os.path.join(output_dir, "user_data.json")
        save_json(user_data, user_data_file)
        logger.info(f"User data saved to {user_data_file}")
    else:
        logger.info("User data saved to database")

    # Check for missing skill ratings
    if DATABASE_AVAILABLE and user_id:
        print("\n⚠️ IMPORTANT: We need to collect your skill ratings to help with job applications.")
        print("This information is used to answer questions about your proficiency in various technologies.")

        # Check if user has skills in the database
        try:
            from database.db_integration_main import get_user_skills

            # Get user skills from database
            user_skills = get_user_skills(user_id)

            if user_skills:
                logger.info(f"Found {len(user_skills)} skills in database for user ID: {user_id}")
                print(f"\n✅ Found {len(user_skills)} skills in database:")
                for i, skill in enumerate(user_skills, 1):
                    print(f"{i}. {skill['skill_name']}: {skill['rating']}/10")

                # Ask if user wants to add/update skills
                update_skills = input("\nDo you want to add/update your skill ratings? (y/n): ").strip().lower() == 'y'

                if update_skills:
                    # Call the skill rating manager
                    logger.info("User chose to update skills")
                    print("\n📊 Running skill rating manager...")

                    # Call the script as a subprocess
                    import subprocess
                    skill_rating_script = os.path.join(os.path.dirname(__file__), "manage_skill_ratings.py")

                    if os.path.exists(skill_rating_script):
                        # Run the script with the email as an argument
                        subprocess.run([sys.executable, skill_rating_script, email], check=True)
                        logger.info("Skill rating collection completed")
                    else:
                        logger.error(f"Skill rating script not found: {skill_rating_script}")
                        print(f"\n❌ Skill rating script not found: {skill_rating_script}")
                else:
                    logger.info("User chose not to update skills")
                    print("\n✅ Using existing skill ratings")
            else:
                logger.info(f"No skills found in database for user ID: {user_id}")
                print("\n⚠️ No skills found in database. Let's add some!")

                # Call the skill rating manager
                logger.info("Calling manage_skill_ratings.py script")
                print("\n📊 Running skill rating manager...")

                # Call the script as a subprocess
                import subprocess
                skill_rating_script = os.path.join(os.path.dirname(__file__), "manage_skill_ratings.py")

                if os.path.exists(skill_rating_script):
                    # Run the script with the email as an argument
                    subprocess.run([sys.executable, skill_rating_script, email], check=True)
                    logger.info("Skill rating collection completed")
                else:
                    logger.error(f"Skill rating script not found: {skill_rating_script}")
                    print(f"\n❌ Skill rating script not found: {skill_rating_script}")
        except Exception as e:
            logger.error(f"Error checking user skills: {e}")
            print(f"\n❌ Error checking user skills: {e}")

            # Fall back to calling the skill rating manager directly
            try:
                logger.info("Falling back to calling manage_skill_ratings.py script directly")
                print("\n📊 Running skill rating manager...")

                # Call the script as a subprocess
                import subprocess
                skill_rating_script = os.path.join(os.path.dirname(__file__), "manage_skill_ratings.py")

                if os.path.exists(skill_rating_script):
                    # Run the script with the email as an argument
                    subprocess.run([sys.executable, skill_rating_script, email], check=True)
                    logger.info("Skill rating collection completed")
                else:
                    logger.error(f"Skill rating script not found: {skill_rating_script}")
                    print(f"\n❌ Skill rating script not found: {skill_rating_script}")
            except Exception as e:
                logger.error(f"Error in skill rating collection: {e}")
                print(f"\n❌ Error collecting skill ratings: {e}")

    # Check for certifications
    if DATABASE_AVAILABLE and user_id:
        print("\n⚠️ IMPORTANT: We need to collect your certifications to help with job applications.")
        print("This information is used to answer questions about your certifications during interviews.")

        # Check if user has certifications in the database
        try:
            from database.db_integration_main import get_user_certifications

            # Get user certifications from database
            user_certifications = get_user_certifications(user_id)

            if user_certifications:
                logger.info(f"Found {len(user_certifications)} certifications in database for user ID: {user_id}")
                print(f"\n✅ Found {len(user_certifications)} certifications in database:")
                for i, cert in enumerate(user_certifications, 1):
                    print(f"{i}. {cert['certification_name']} ({cert['issuing_organization'] if cert['issuing_organization'] else 'No organization'})")

                # Ask if user wants to add more certifications
                update_certs = input("\nDo you want to add more certifications? (y/n): ").strip().lower() == 'y'

                if update_certs:
                    # Call the certification manager
                    logger.info("User chose to add more certifications")
                    print("\n📜 Running certification manager...")

                    # Call the script as a subprocess
                    import subprocess
                    cert_script = os.path.join(os.path.dirname(__file__), "manage_certifications.py")

                    if os.path.exists(cert_script):
                        # Run the script with the email as an argument
                        subprocess.run([sys.executable, cert_script, email], check=True)
                        logger.info("Certification collection completed")
                    else:
                        logger.error(f"Certification script not found: {cert_script}")
                        print(f"\n❌ Certification script not found: {cert_script}")
                else:
                    logger.info("User chose not to add more certifications")
                    print("\n✅ Using existing certifications")
            else:
                logger.info(f"No certifications found in database for user ID: {user_id}")
                print("\n⚠️ No certifications found in database. Let's add some!")

                # Call the certification manager
                logger.info("Calling manage_certifications.py script")
                print("\n📜 Running certification manager...")

                # Call the script as a subprocess
                import subprocess
                cert_script = os.path.join(os.path.dirname(__file__), "manage_certifications.py")

                if os.path.exists(cert_script):
                    # Run the script with the email as an argument
                    subprocess.run([sys.executable, cert_script, email], check=True)
                    logger.info("Certification collection completed")
                else:
                    logger.error(f"Certification script not found: {cert_script}")
                    print(f"\n❌ Certification script not found: {cert_script}")
        except Exception as e:
            logger.error(f"Error checking user certifications: {e}")
            print(f"\n❌ Error checking user certifications: {e}")

            # Fall back to calling the certification manager directly
            try:
                logger.info("Falling back to calling manage_certifications.py script directly")
                print("\n📜 Running certification manager...")

                # Call the script as a subprocess
                import subprocess
                cert_script = os.path.join(os.path.dirname(__file__), "manage_certifications.py")

                if os.path.exists(cert_script):
                    # Run the script with the email as an argument
                    subprocess.run([sys.executable, cert_script, email], check=True)
                    logger.info("Certification collection completed")
                else:
                    logger.error(f"Certification script not found: {cert_script}")
                    print(f"\n❌ Certification script not found: {cert_script}")
            except Exception as e:
                logger.error(f"Error in certification collection: {e}")
                print(f"\n❌ Error collecting certifications: {e}")

    # Check if user profile exists
    profile_exists = user_manager.profile_exists(email)

    if profile_exists:
        # Ask user if they want to use existing profile or create a new one
        print(f"\n✅ Found existing Chrome profile for {email}")
        use_existing = input("Do you want to use the existing profile? (y/n): ").strip().lower() == 'y'

        if use_existing:
            # Get existing profile
            profile_path = user_manager.get_profile_path(email)
            logger.info(f"Using existing profile at: {profile_path}")

            # Update user data with Chrome profile path
            if DATABASE_AVAILABLE and user_id:
                # Update user data in database
                user_data["chrome_profile_path"] = profile_path
                save_user_data(user_data)
                logger.info(f"Updated Chrome profile path in database for user ID: {user_id}")
        else:
            # List available Chrome profiles
            print("\n📋 Available Chrome profiles:")
            chrome_profiles = JobApplier.list_chrome_profiles()

            for i, profile in enumerate(chrome_profiles):
                print(f"{i+1}. {profile['name']} ({profile['type']})")

            # Ask user to select a profile
            try:
                choice = input("\nSelect a profile number (or press Enter to create a new profile): ").strip()

                if choice:
                    choice = int(choice) - 1
                    if 0 <= choice < len(chrome_profiles):
                        selected_profile = chrome_profiles[choice]
                        profile_path = selected_profile['path']
                        print(f"Selected profile: {selected_profile['name']}")

                        # Associate this Chrome profile with the user email
                        user_manager.associate_profile(email, profile_path)
                        logger.info(f"Associated {email} with Chrome profile at: {profile_path}")
                    else:
                        print("Invalid selection. Creating a new profile.")
                        profile_path = user_manager.create_profile(email)
                        logger.info(f"Created new profile at: {profile_path}")
                else:
                    # Create a new profile
                    profile_path = user_manager.create_profile(email)
                    logger.info(f"Created new profile at: {profile_path}")
            except (ValueError, IndexError):
                print("Invalid selection. Creating a new profile.")
                profile_path = user_manager.create_profile(email)
                logger.info(f"Created new profile at: {profile_path}")
    else:
        # No existing profile, create a new one
        print(f"\n⚠️ No existing Chrome profile found for {email}")
        print("Creating a new dedicated Chrome profile for auto job application...")

        # Set default to create a new profile
        use_existing_chrome = False

        if use_existing_chrome:
            # List available Chrome profiles
            print("\n📋 Available Chrome profiles:")
            chrome_profiles = JobApplier.list_chrome_profiles()

            for i, profile in enumerate(chrome_profiles):
                print(f"{i+1}. {profile['name']} ({profile['type']})")

            # Ask user to select a profile
            try:
                choice = input("\nSelect a profile number (or press Enter to create a new profile): ").strip()

                if choice:
                    choice = int(choice) - 1
                    if 0 <= choice < len(chrome_profiles):
                        selected_profile = chrome_profiles[choice]
                        profile_path = selected_profile['path']
                        print(f"Selected profile: {selected_profile['name']}")

                        # Associate this Chrome profile with the user email
                        user_manager.associate_profile(email, profile_path)
                        logger.info(f"Associated {email} with Chrome profile at: {profile_path}")
                    else:
                        print("Invalid selection. Creating a new profile.")
                        profile_path = user_manager.create_profile(email)
                        logger.info(f"Created new profile at: {profile_path}")
                else:
                    # Create a new profile
                    profile_path = user_manager.create_profile(email)
                    logger.info(f"Created new profile at: {profile_path}")
            except (ValueError, IndexError):
                print("Invalid selection. Creating a new profile.")
                profile_path = user_manager.create_profile(email)
                logger.info(f"Created new profile at: {profile_path}")
        else:
            # Create a new profile
            profile_path = user_manager.create_profile(email)
            logger.info(f"Created new profile at: {profile_path}")

    # Initialize job applier
    job_applier = JobApplier(chrome_profile_path=profile_path, headless=args.headless)

    # Parse resume if in full or parse mode
    resume_data = None
    resume_path = None
    if args.mode in ['full', 'parse']:
        # Get resume path
        resume_path = args.resume
        if not resume_path:
            resume_path = input("Please enter path to your resume (PDF or DOCX): ").strip()

        # Use the resume parser module directly
        logger.info(f"Parsing resume: {resume_path}")
        resume_text = extract_resume_text(resume_path)
        if not resume_text:
            logger.error("Failed to extract text from resume")
            return 1

        # Save resume text to database if available
        if DATABASE_AVAILABLE and user_id:
            logger.info(f"Saving resume text to database for user ID: {user_id}")
            update_success = update_user_resume(user_id, resume_path, resume_text)
            if update_success:
                logger.info(f"Successfully saved resume text to database for user ID: {user_id}")
                print(f"✅ Resume text saved to database")
            else:
                logger.warning(f"Failed to save resume text to database for user ID: {user_id}")
                print(f"⚠️ Failed to save resume text to database")

        # Extract and clean skills
        extracted_skills = extract_skills(resume_text)
        cleaned_skills = clean_skills(extracted_skills)
        deduped_skills = deduplicate_skills(cleaned_skills)

        # Save skills to file
        skills_file = os.path.join(output_dir, "resume_skills.json")
        skills_data = {
            "extracted_skills": extracted_skills,
            "cleaned_skills": cleaned_skills,
            "deduped_skills": deduped_skills
        }
        save_json(skills_data, skills_file)

        # Display extracted skills
        print("\n✅ Extracted Skills:")
        for skill in deduped_skills:
            print(f"- {skill}")

        # Check if user has previous search preferences
        previous_preferences = None
        use_previous = False

        if DATABASE_AVAILABLE and user_id:
            previous_preferences = get_search_preferences(user_id)

            if previous_preferences:
                print("\n✅ Found previous search preferences:")
                print(f"Job Roles: {', '.join(previous_preferences['job_roles'])}")
                print(f"Locations: {', '.join(previous_preferences['locations'])}")
                print(f"Skills: {', '.join(previous_preferences['skills'])}")
                # print(f"Industry Filters: {', '.join(previous_preferences['industries'])}")
                # print(f"Department Filters: {', '.join(previous_preferences['departments'])}")
                
                # Display industries if they exist
                industries = previous_preferences.get('industries',[])
                if industries:
                    print(f"Industry Filters: {', '.join(industries)}")
                else:
                    print("Industries Filters: None")
                
                # Display departments if they exist
                departments = previous_preferences.get('departments',[])
                if industries:
                    print(f"Departments Filters: {', '.join(departments)}")
                else:
                    print("Departments Filters: None")

                # Ask if user wants to modify industry filters
                modify_industries = input("\n❓ Do you want to add/modify industry filters? (y/n): ").lower() == 'y'
                if modify_industries:
                    # Define industry types available on Naukri
                    industry_types = [
                        "IT Services & Consulting",
                        "BPM / BPO",
                        "Analytics / KPO / Research",
                        "Software Product",
                        "Internet",
                        "Electronic Components / Semiconductors",
                        "Electronics Manufacturing",
                        "Emerging Technologies",
                        "Hardware & Networking",
                        "Recruitment / Staffing",
                        "Management Consulting",
                        "Accounting / Auditing",
                        "Architecture / Interior Design",
                        "Facility Management Services",
                        "Design",
                        "Law Enforcement / Security Services",
                        "Legal",
                        "Content Development / Language",
                        "Banking",
                        "Financial Services",
                        "Investment Banking / Venture Capital / Private Equity",
                        "Insurance",
                        "FinTech / Payments",
                        "NBFC",
                        "Medical Services / Hospital",
                        "Pharmaceutical & Life Sciences",
                        "Biotechnology",
                        "Medical Devices & Equipment",
                        "Clinical Research / Contract Research",
                        "Education / Training",
                        "E-Learning / EdTech",
                        "Advertising & Marketing",
                        "Telecom / ISP",
                        "Film / Music / Entertainment",
                        "Gaming",
                        "TV / Radio",
                        "Printing & Publishing",
                        "Animation & VFX",
                        "Events / Live Entertainment",
                        "Sports / Leisure & Recreation",
                        "Industrial Equipment / Machinery",
                        "Automobile",
                        "Auto Components",
                        "Defence & Aerospace",
                        "Industrial Automation",
                        "Building Material",
                        "Electrical Equipment",
                        "Petrochemical / Plastics / Rubber",
                        "Chemicals",
                        "Packaging & Containers",
                        "Iron & Steel",
                        "Pulp & Paper",
                        "Fertilizers / Pesticides / Agro chemicals",
                        "Metals & Mining",
                        "Engineering & Construction",
                        "Power",
                        "Real Estate",
                        "Courier / Logistics",
                        "Oil & Gas",
                        "Aviation",
                        "Railways",
                        "Ports & Shipping",
                        "Water Treatment / Waste Management",
                        "Urban Transport",
                        "Retail",
                        "Consumer Electronics & Appliances",
                        "Textile & Apparel",
                        "Travel & Tourism",
                        "FMCG",
                        "Hotels & Restaurants",
                        "Fitness & Wellness",
                        "Food Processing",
                        "Beverage",
                        "Furniture & Furnishing",
                        "Gems & Jewellery",
                        "NGO / Social Services / Industry Associations",
                        "Agriculture / Forestry / Fishing",
                        "Government / Public Administration",
                        "Import & Export"
                    ]
                    # Display industry types
                    print("\nAvailable Industry Types:")
                    for i, industry in enumerate(industry_types, 1):
                        print(f"{i}. {industry}")
                    
                    # Allow multiple selections
                    selected_industries = []
                    while True:
                        industry_input = input("\nEnter industry number (or 0 to finish selection): ").strip()
                        if industry_input == "0":
                            break
                        
                        if industry_input.isdigit() and 1 <= int(industry_input) <= len(industry_types):
                            selected_index = int(industry_input) - 1
                            selected_industry = industry_types[selected_index]
                            if selected_industry not in selected_industries:
                                # Add the selected industry if not already in list
                                selected_industries.append(selected_industry)
                                print(f"✅ Added {selected_industry}")
                                print(f"Current selections: {', '.join(selected_industries)}")
                            else:
                                print(f"⚠️ {selected_industry} already selected")
                        else:
                            print(f"⚠️ Please enter a valid number between 1 and {len(industry_types)}, or 0 to finish")
                    
                    if selected_industries:
                        # Update the previous preferences with the new selections
                        previous_preferences['industries'] = selected_industries
                        industries = selected_industries

                        # Save ONLY the updated industries to the database
                        if DATABASE_AVAILABLE and user_id:
                            preference_id = save_search_preferences(
                                user_id=user_id,
                                job_roles=previous_preferences['job_roles'],  # Use existing roles
                                locations=previous_preferences["locations"],  # Use existing locations
                                skills=previous_preferences['skills'],        # Use existing skills
                                industries=selected_industries,               # Use new industries
                                departments=previous_preferences.get('departments', [])   # Use existing departments
                            )

                            if preference_id:
                                print(f"\n✅ Industry preferences updated in database: {', '.join(selected_industries)}")

                # Ask if user wants to modify department filters
                # modify_departments = input("\n❓ Do you want to add/modify department filters? (y/n): ").strip().lower() == 'y'
                # if modify_departments:
                #     # Define departments available on Naukri
                #     departments = [
                #             "Engineering - Software & QA",
                #             "Data Science & Analytics",
                #             "Engineering - Hardware & Networks",
                #             "IT & Information Security",
                #             "Customer Success, Service & Operations",
                #             "Finance & Accounting",
                #             "Quality Assurance",
                #             "Other",
                #             "Healthcare & Life Sciences",
                #             "Consulting",
                #             "Sales & Business Development",
                #             "Research & Development",
                #             "UX, Design & Architecture",
                #             "Marketing & Communication",
                #             "Teaching & Training",
                #             "Investments & Trading",
                #             "Construction & Site Engineering",
                #             "Product Management",
                #             "Project & Program Management",
                #             "Content, Editorial & Journalism",
                #             "Procurement & Supply Chain",
                #             "Human Resources",
                #             "Risk Management & Compliance",
                #             "Food, Beverage & Hospitality",
                #             "Merchandising, Retail & eCommerce",
                #             "Administration & Facilities",
                #             "Media Production & Entertainment",
                #             "Strategic & Top Management",
                #             "Environment Health & Safety",
                #             "Legal & Regulatory",
                #             "Aviation & Aerospace",
                #             "CSR & Social Service",
                #             "Sports, Fitness & Personal Care"
                #         ]
                #     # Display departments
                #     print("\nAvailable Departments:")
                #     for i, department in enumerate(departments, 1):
                #         print(f"{i}. {department}")
                    
                #     # Allow multiple selections
                #     selected_departments = []
                #     while True:
                #         department_input = input("\nEnter department number (or 0 to finish selection): ").strip()
                #         if department_input == "0":
                #             break

                #         if department_input.isdigit() and 1 <= int(department_input) <= len(departments):
                #             selected_index = int(department_input) - 1
                #             selected_department = departments[selected_index]
                #             if selected_department not in selected_departments:
                #                 # Add the selected department if not already in list
                #                 selected_departments.append(selected_department)
                #                 print(f"✅ Added {selected_department}")
                #                 print(f"Current selections: {', '.join(selected_departments)}")
                #             else:
                #                 print(f"⚠️ {selected_department} already selected")
                #         else:
                #             print(f"⚠️ Please enter a valid number between 1 and {len(departments)}, or 0 to finish")

                #     if selected_departments:
                #         # Update the previous preferences with the new selections
                #         previous_preferences['departments'] = selected_departments
                #         departments = selected_departments



                # we need to ask user wanted to add the industry filters
                # is yes the We need to move the industry realted code here from the main.py(current file) inluding calling the select_multiple_industries function.
                    # and the user selected industries need to be added to the database here as comma seperated values.
                # else no then go to next question 
                # we need to ask user wanted to add the department fitlers
                # if yes then we need to move the department realted code here from the main.py(current file) inluding calling the select_multiple_departments function.
                    # and the user selected departments need to be added to the database here as comma seperated values.
                # else no then continue

                use_previous = input("\n❓ Do you want to use these previous search preferences? (y/n): ").strip().lower() == 'y'

                if use_previous:
                    search_skills = previous_preferences['skills']
                    print(f"\n✅ Using previous search skills: {', '.join(search_skills)}")

                    # Skip the interactive skill selection
                    goto_skill_confirmation = True
                else:
                    goto_skill_confirmation = False
            else:
                goto_skill_confirmation = False
        else:
            goto_skill_confirmation = False

        # If not using previous preferences, do the interactive skill selection
        if not goto_skill_confirmation:
            # Use the interactive checkbox selection from resume_parser
            print("\n🔍 Select skills for job search:")
            print("These skills will be used in job search queries.")
            search_skills = selected_search_skills(deduped_skills)

        # Ask for additional skills
        extra_input = input("⚠️ No skills matching 🤔, or \n➕ Want to add any more skills? Type comma-separated values (or press Enter to skip): ")
        if extra_input:
            extra_skills = [s.strip() for s in extra_input.split(",") if s.strip()]
            search_skills.extend(extra_skills)

        # Deduplicate skills
        search_skills = deduplicate_skills(search_skills)
        print(f"\n✅ Final search skills: {search_skills}")

        # Confirm skills before continuing
        confirm = input("❓Want to remove any skill before continuing? We will use these selected skills to search for jobs (Type comma-separated or press Enter to continue): ").strip()
        if confirm:
            to_remove = [s.strip().lower() for s in confirm.split(",") if s.strip()]
            search_skills = [
                s for s in search_skills
                if not any(remove in s.lower() for remove in to_remove)]
            print(f"\n✅ Updated search skills: {search_skills}")
        
        # Ask if user wants to modify industry filters
        modify_industries = input("\n❓ Do you want to add/modify industry filters? (y/n): ").lower() == 'y'
        if modify_industries:
            # Define industry types available on Naukri
            industry_types = [
                "IT Services & Consulting",
                "BPM / BPO",
                "Analytics / KPO / Research",
                "Software Product",
                "Internet",
                "Electronic Components / Semiconductors",
                "Electronics Manufacturing",
                "Emerging Technologies",
                "Hardware & Networking",
                "Recruitment / Staffing",
                "Management Consulting",
                "Accounting / Auditing",
                "Architecture / Interior Design",
                "Facility Management Services",
                "Design",
                "Law Enforcement / Security Services",
                "Legal",
                "Content Development / Language",
                "Banking",
                "Financial Services",
                "Investment Banking / Venture Capital / Private Equity",
                "Insurance",
                "FinTech / Payments",
                "NBFC",
                "Medical Services / Hospital",
                "Pharmaceutical & Life Sciences",
                "Biotechnology",
                "Medical Devices & Equipment",
                "Clinical Research / Contract Research",
                "Education / Training",
                "E-Learning / EdTech",
                "Advertising & Marketing",
                "Telecom / ISP",
                "Film / Music / Entertainment",
                "Gaming",
                "TV / Radio",
                "Printing & Publishing",
                "Animation & VFX",
                "Events / Live Entertainment",
                "Sports / Leisure & Recreation",
                "Industrial Equipment / Machinery",
                "Automobile",
                "Auto Components",
                "Defence & Aerospace",
                "Industrial Automation",
                "Building Material",
                "Electrical Equipment",
                "Petrochemical / Plastics / Rubber",
                "Chemicals",
                "Packaging & Containers",
                "Iron & Steel",
                "Pulp & Paper",
                "Fertilizers / Pesticides / Agro chemicals",
                "Metals & Mining",
                "Engineering & Construction",
                "Power",
                "Real Estate",
                "Courier / Logistics",
                "Oil & Gas",
                "Aviation",
                "Railways",
                "Ports & Shipping",
                "Water Treatment / Waste Management",
                "Urban Transport",
                "Retail",
                "Consumer Electronics & Appliances",
                "Textile & Apparel",
                "Travel & Tourism",
                "FMCG",
                "Hotels & Restaurants",
                "Fitness & Wellness",
                "Food Processing",
                "Beverage",
                "Furniture & Furnishing",
                "Gems & Jewellery",
                "NGO / Social Services / Industry Associations",
                "Agriculture / Forestry / Fishing",
                "Government / Public Administration",
                "Import & Export"
            ]
            # Display industry types
            print("\nAvailable Industry Types:")
            for i, industry in enumerate(industry_types, 1):
                print(f"{i}. {industry}")
            
            # Allow multiple selections
            selected_industries = []
            while True:
                industry_input = input("\nEnter industry number (or 0 to finish selection): ").strip()
                if industry_input == "0":
                    break
                
                if industry_input.isdigit() and 1 <= int(industry_input) <= len(industry_types):
                    selected_index = int(industry_input) - 1
                    selected_industry = industry_types[selected_index]
                    if selected_industry not in selected_industries:
                        # Add the selected industry if not already in list
                        selected_industries.append(selected_industry)
                        print(f"✅ Added {selected_industry}")
                        print(f"Current selections: {', '.join(selected_industries)}")
                    else:
                        print(f"⚠️ {selected_industry} already selected")
                else:
                    print(f"⚠️ Please enter a valid number between 1 and {len(industry_types)}, or 0 to finish")
            
            if selected_industries:
                # Update the previous preferences with the new selections
                previous_preferences['industries'] = selected_industries
                industries = selected_industries

        # Ask if user wants to modify department filters
        modify_departments = input("\n❓ Do you want to add/modify department filters? (y/n): ").strip().lower() == 'y'
        if modify_departments:
            # Define departments available on Naukri
            departments = [
                    "Engineering - Software & QA",
                    "Data Science & Analytics",
                    "Engineering - Hardware & Networks",
                    "IT & Information Security",
                    "Customer Success, Service & Operations",
                    "Finance & Accounting",
                    "Quality Assurance",
                    "Other",
                    "Healthcare & Life Sciences",
                    "Consulting",
                    "Sales & Business Development",
                    "Research & Development",
                    "UX, Design & Architecture",
                    "Marketing & Communication",
                    "Teaching & Training",
                    "Investments & Trading",
                    "Construction & Site Engineering",
                    "Product Management",
                    "Project & Program Management",
                    "Content, Editorial & Journalism",
                    "Procurement & Supply Chain",
                    "Human Resources",
                    "Risk Management & Compliance",
                    "Food, Beverage & Hospitality",
                    "Merchandising, Retail & eCommerce",
                    "Administration & Facilities",
                    "Media Production & Entertainment",
                    "Strategic & Top Management",
                    "Environment Health & Safety",
                    "Legal & Regulatory",
                    "Aviation & Aerospace",
                    "CSR & Social Service",
                    "Sports, Fitness & Personal Care"
                ]
            # Display departments
            print("\nAvailable Departments:")
            for i, department in enumerate(departments, 1):
                print(f"{i}. {department}")
            
            # Allow multiple selections
            selected_departments = []
            while True:
                department_input = input("\nEnter department number (or 0 to finish selection): ").strip()
                if department_input == "0":
                    break

                if department_input.isdigit() and 1 <= int(department_input) <= len(departments):
                    selected_index = int(department_input) - 1
                    selected_department = departments[selected_index]
                    if selected_department not in selected_departments:
                        # Add the selected department if not already in list
                        selected_departments.append(selected_department)
                        print(f"✅ Added {selected_department}")
                        print(f"Current selections: {', '.join(selected_departments)}")
                    else:
                        print(f"⚠️ {selected_department} already selected")
                else:
                    print(f"⚠️ Please enter a valid number between 1 and {len(departments)}, or 0 to finish")

            if selected_departments:
                # Update the previous preferences with the new selections
                previous_preferences['departments'] = selected_departments
                departments = selected_departments

        # Create resume data
        resume_data = {
            "text": resume_text,
            "skills": deduped_skills,
            "search_skills": search_skills,
            "file_path": resume_path
        }

        # Save resume data
        resume_file = os.path.join(output_dir, "resume_data.json")
        save_json(resume_data, resume_file)

    # Search for jobs if in full or search mode
    job_links = []
    if args.mode in ['full', 'search']:
        # Check if we already have search preferences from resume parsing
        if 'goto_skill_confirmation' in locals() and goto_skill_confirmation and use_previous:
            # We already have the skills from previous preferences
            # Now get roles and locations from previous preferences
            roles = previous_preferences['job_roles']
            locations = previous_preferences['locations']
            skills = search_skills  # Already set during resume parsing

            # Get industry and department preferences if they exist
            industries = previous_preferences.get('industries', [])
            departments = previous_preferences.get('departments', [])

            print(f"\n✅ Using previous search preferences")
            print(f"Job Roles: {', '.join(roles)}")
            print(f"Locations: {', '.join(locations)}")
            print(f"Skills: {', '.join(skills)}")

            if industries:
                print(f"Industries: {', '.join(industries)}")

            if departments:
                print(f"Departments: {', '.join(departments)}")
        else:
            # Get roles
            roles = args.roles.split(',') if args.roles else None
            if not roles:
                roles_input = input("Enter job roles (comma-separated, e.g., Data Analyst, Business Analyst): ")
                roles = [r.strip() for r in roles_input.split(",") if r.strip()]

            # Get locations
            locations = args.locations.split(',') if args.locations else None
            if not locations:
                locations_input = input("Enter preferred locations (comma-separated, e.g., Hyderabad, Bangalore, Remote): ")
                locations = [l.strip() for l in locations_input.split(",") if l.strip()]

            # Get skills
            skills = args.skills.split(',') if args.skills else None
            if not skills:
                if resume_data and "search_skills" in resume_data:
                    skills = resume_data["search_skills"]
                else:
                    skills_input = input("Enter search skills (comma-separated): ")
                    skills = [s.strip() for s in skills_input.split(",") if s.strip()]

            # Save search preferences to database
            if DATABASE_AVAILABLE and user_id:
                # Get industry and department preferences if they were selected
                industries = []
                departments = []

                if 'selected_industries' in locals() and selected_industries:
                    industries = selected_industries

                if 'selected_departments' in locals() and selected_departments:
                    departments = selected_departments

                preference_id = save_search_preferences(
                    user_id=user_id,
                    job_roles=roles,
                    locations=locations,
                    skills=skills,
                    industries=industries,
                    departments=departments
                )

                if preference_id:
                    print(f"\n✅ Search preferences saved to database")

                    # Log the saved preferences
                    if industries:
                        print(f"✅ Industry preferences saved: {', '.join(industries)}")

                    if departments:
                        print(f"✅ Department preferences saved: {', '.join(departments)}")
                else:
                    print(f"\n❌ Failed to save search preferences to database")

        # Search for jobs
        logger.info(f"Searching for jobs: roles={roles}, locations={locations}, skills={skills}")

        # Use Naukri handler for job search with Selenium
        logger.info("Using Naukri handler for job search with Selenium")

        # Ask for experience
        experience_input = input("Enter minimum experience (e.g., 0+, 1+, 2+): ") or "0+"
        experience = experience_input.strip().replace("+", "")

        # Ask for freshness
        freshness_input = input("Enter job freshness (1= Last 1 day, 3= Last 3 days, 7=1 week, 15=15 days, 30=Last 30 Days): ") or ""
        freshness = freshness_input.strip() if freshness_input else None

        # Use our Selenium-based Naukri search function
        print("\n🔍 Searching for jobs on Naukri.com using Selenium")
        job_links = search_naukri_with_selenium(
            profile_path=profile_path,
            roles=roles,
            locations=locations,
            experience=experience,
            freshness=freshness,
            max_jobs=args.max_jobs,
            industries = industries,
            departments = departments
        )

        if job_links:
            print(f"✅ Found {len(job_links)} job links")
        else:
            # Fall back to regular job search
            print("❌ No job links found with Selenium. Falling back to regular job search.")
            logger.info("Falling back to regular job search")
            if resume_path:
                # Use integrated search pipeline
                logger.info("Using integrated search pipeline")
                job_links, _ = integrated_search_pipeline(resume_path, roles, locations, pre_selected_skills=skills)
            else:
                # Use regular job search
                logger.info("Using regular job search")
                job_links = run_job_search(roles, locations, skills)

            if not job_links:
                print("❌ No job links found with fallback method either")
                return 1

        if not job_links:
            logger.error("No job links found")
            return 1

        # Save job links to database if available
        if DATABASE_AVAILABLE and user_id:
            # Prepare job data for database
            db_jobs = []
            for job_url in job_links:
                db_job = {
                    "job_url": job_url,
                    "job_portal": "naukri",
                    "job_title": "To be extracted",
                    "company_name": "To be extracted",
                    "location": "To be extracted",
                    "extraction_date": datetime.now().date().isoformat(),
                    "status": "pending",
                    "industry_type": "To be extracted",
                    "employment_type": "To be extracted",
                    "role_category": "To be extracted",
                    "posting_date": datetime.now().date().isoformat()
                }
                db_jobs.append(db_job)

            # Save to database
            job_ids = save_job_listings(user_id, db_jobs)
            if job_ids:
                logger.info(f"Saved {len(job_ids)} job links to database")
                print(f"✅ Saved {len(job_ids)} job links to database")
            else:
                logger.error("Failed to save job links to database")
                print("❌ Failed to save job links to database")

        # Save to file only if database is not available
        if not DATABASE_AVAILABLE:
            links_file = os.path.join(output_dir, "job_links.json")
            links_data = {
                "roles": roles,
                "locations": locations,
                "skills": skills,
                "links": job_links
            }
            save_json(links_data, links_file)
            logger.info(f"Job links saved to {links_file}")
    else:
        # Try to load job links from file
        links_data = load_json(os.path.join(output_dir, "job_links.json"))
        if links_data and "links" in links_data:
            job_links = links_data["links"]
            logger.info(f"Loaded {len(job_links)} job links from file")

    # Extract job details if in full, search, or match mode
    job_details = []
    if args.mode in ['full', 'search', 'match'] and job_links:
        # Limit number of jobs
        job_links = job_links[:args.max_jobs]

        # We don't need to start the Playwright browser for job details extraction
        # since we're using Selenium directly

        # Extract job details
        logger.info(f"Extracting details from {len(job_links)} jobs")
        print(f"\n🔍 Extracting details from {len(job_links)} jobs")

        # Process each job link sequentially
        for i, job_url in enumerate(job_links):
            logger.info(f"Processing job {i+1}/{len(job_links)}: {job_url}")
            print(f"\n🔍 Processing job {i+1}/{len(job_links)}: {job_url}")

            # Extract job details using the extract_job_details_from_url function
            details = extract_job_details_from_url(
                job_url=job_url,
                profile_path=profile_path,
                headless=args.headless,
                timeout=60
            )

            if details and "role" in details and details["role"] != "Unknown Role":
                # Add URL to details if not already present
                if "url" not in details:
                    details["url"] = job_url

                # Add to job details list
                job_details.append(details)
                logger.info(f"Extracted details for job: {details.get('role', 'Unknown')}")
                print(f"✅ Successfully extracted details for job: {details.get('role', 'Unknown')}")
            else:
                logger.warning(f"Failed to extract details for job: {job_url}")
                print(f"❌ Failed to extract job details for: {job_url}")

        # Save job details to database if available
        if DATABASE_AVAILABLE and user_id:
            # Prepare job data for database
            db_jobs = []
            for job in job_details:
                db_job = {
                    "job_url": job.get("url", ""),
                    "job_portal": "naukri",
                    "job_title": job.get("role", "Unknown"),
                    "company_name": job.get("company_name", job.get("company", "Unknown")),  # Try both company_name and company
                    "location": job.get("location", "Unknown"),
                    "experience_required": job.get("experience", ""),
                    "salary": job.get("salary", ""),
                    "job_description": job.get("job_description", ""),
                    "skills_required": ",".join(job.get("skills", [])) if isinstance(job.get("skills"), list) else job.get("skills", ""),
                    "apply_type": job.get("apply_type", "direct"),
                    "extraction_date": datetime.now().date().isoformat(),
                    "status": "pending",
                    "industry_type": job.get("industry_type", "Not specified"),
                    "education": job.get("education", "Not specified"),
                    "employment_type": job.get("employment_type", "Not specified"),
                    "role_category": job.get("role_category", "Not specified"),
                    "posting_date": job.get("actual_posting_date", None) or job.get("posting_date", None)
                }
                db_jobs.append(db_job)

            # Save to database
            job_ids = save_job_listings(user_id, db_jobs)
            if job_ids:
                logger.info(f"Saved {len(job_ids)} job listings to database")
                print(f"✅ Saved {len(job_ids)} job listings to database")

                # Add job_id to job_details for future reference
                for i, job_id in enumerate(job_ids):
                    if i < len(job_details):
                        job_details[i]["job_id"] = job_id
            else:
                logger.error("Failed to save job listings to database")
                print("❌ Failed to save job listings to database")

        # Save to file only if database is not available
        if not DATABASE_AVAILABLE:
            details_file = os.path.join(output_dir, "job_details.json")
            save_json(job_details, details_file)
            logger.info(f"Job details saved to {details_file}")
        else:
            logger.info("Job details saved to database")

        if not job_details:
            logger.error("Failed to extract job details")
            return 1
    else:
        # Try to get jobs from database first if available
        if DATABASE_AVAILABLE and user_id:
            # Get recent jobs from database
            db_jobs = get_recent_jobs(user_id, days=7, limit=args.max_jobs)
            if db_jobs:
                logger.info(f"Retrieved {len(db_jobs)} recent jobs from database")
                print(f"✅ Retrieved {len(db_jobs)} recent jobs from database")

                # Convert database jobs to job_details format as a dictionary keyed by job_id
                job_details = {}
                for job in db_jobs:
                    job_id = job.get("job_id")
                    if job_id is not None:
                        job_detail = {
                            "job_id": job_id,
                            "url": job.get("job_url", ""),
                            "role": job.get("job_title", "Unknown"),
                            "company_name": job.get("company_name", "Unknown"),
                            "location": job.get("location", "Unknown"),
                            "experience": job.get("experience_required", ""),
                            "salary": job.get("salary", ""),
                            "job_description": job.get("job_description", ""),
                            "skills": job.get("skills_required", "").split(",") if job.get("skills_required") else [],
                            "apply_type": job.get("apply_type", "direct"),
                            "extraction_date": job.get("extraction_date", ""),
                            "industry_type": job.get("industry_type", "Not specified"),
                            "education": job.get("education", "Not specified"),
                            "employment_type": job.get("employment_type", "Not specified"),
                            "role_category": job.get("role_category", "Not specified"),
                            "posting_date": job.get("posting_date", ""),
                            "actual_posting_date": job.get("posting_date", "")
                        }
                        job_details[job_id] = job_detail
            else:
                # Fall back to file-based storage
                details_data = load_json(os.path.join(output_dir, "job_details.json"))
                if details_data:
                    job_details = details_data
                    logger.info(f"Loaded {len(job_details)} job details from file")
        else:
            # Try to load job details from file
            details_data = load_json(os.path.join(output_dir, "job_details.json"))
            if details_data:
                job_details = details_data
                logger.info(f"Loaded {len(job_details)} job details from file")

    # Match jobs if in full, match, or apply mode
    ranked_jobs = []
    if args.mode in ['full', 'match', 'apply'] and job_details:
        # Check if we need to get resume path for match mode
        if args.mode == 'match' and not resume_path:
            if args.resume:
                resume_path = args.resume
            else:
                # Ask for resume path if not provided
                resume_path = input("Please enter path to your resume (PDF or DOCX): ").strip()

            # If resume path is provided, process it now
            if resume_path:
                logger.info(f"Parsing resume for match mode: {resume_path}")
                resume_text = extract_resume_text(resume_path)
                if resume_text:
                    # Save resume text to database if available
                    if DATABASE_AVAILABLE and user_id:
                        logger.info(f"Saving resume text to database for user ID: {user_id}")
                        update_success = update_user_resume(user_id, resume_path, resume_text)
                        if update_success:
                            logger.info(f"Successfully saved resume text to database for user ID: {user_id}")
                            print(f"✅ Resume text saved to database")
                        else:
                            logger.warning(f"Failed to save resume text to database for user ID: {user_id}")
                            print(f"⚠️ Failed to save resume text to database")

                    # Extract skills from resume text for matching
                    extracted_skills = extract_skills(resume_text)
                    cleaned_skills = clean_skills(extracted_skills)
                    deduped_skills = deduplicate_skills(cleaned_skills)

                    # Create resume data for later use
                    resume_data = {
                        "text": resume_text,
                        "skills": deduped_skills,
                        "file_path": resume_path
                    }
                else:
                    logger.warning("Failed to extract text from resume")

        # Get resume skills
        resume_skills = []
        if resume_data and "skills" in resume_data:
            resume_skills = resume_data["skills"]
        else:
            # Try to load resume skills from file
            skills_data = load_json(os.path.join(output_dir, "resume_skills.json"))
            if skills_data and "deduped_skills" in skills_data:
                resume_skills = skills_data["deduped_skills"]
            else:
                skills_input = input("Enter resume skills (comma-separated): ")
                resume_skills = [s.strip() for s in skills_input.split(",") if s.strip()]

        # Create a comprehensive profile for matching
        # 1. Start with deduplicated skills from resume
        comprehensive_skills = resume_skills.copy() if resume_skills else []

        # 2. Add user-selected skills if they're not already in the list
        user_skills = []
        if args.skills:
            user_skills = [s.strip() for s in args.skills.split(",") if s.strip()]

        if user_skills:
            for skill in user_skills:
                if skill not in comprehensive_skills:
                    comprehensive_skills.append(skill)

        # 3. Add user-selected roles as skills
        user_roles = []
        if args.roles:
            user_roles = [r.strip() for r in args.roles.split(",") if r.strip()]

        if user_roles:
            for role in user_roles:
                if role not in comprehensive_skills:
                    comprehensive_skills.append(role)

        # Convert to string for matching
        resume_skills_text = ", ".join(comprehensive_skills)

        print(f"\n🔍 Using the following comprehensive profile for matching:")
        print(f"Skills and roles: {resume_skills_text}")

        # Ask user which matching method to use
        print("\n🔍 Choose a job matching method:")
        print("1. LLM-based matching (most accurate, but slower)")
        print("2. TF-IDF matching (faster, based on keyword frequency)")
        print("3. Simple keyword matching (fastest, counts matching skills)")

        match_method = input("Enter your choice (1-3): ").strip() or "1"

        # Import the appropriate matching function based on user's choice
        if match_method == "1":
            # LLM-based matching
            from stages.llm_matcher.llm_job_matcher_optimized import initialize_model, batch_process_jobs

            logger.info(f"Using LLM-based matching for {len(job_details)} jobs")
            print(f"\n🔍 Using LLM-based matching for {len(job_details)} jobs")

            # Initialize the model
            initialize_model()

            # Process jobs in batch with LLM
            # Print the first job details to debug
            if isinstance(job_details, list) and job_details:
                print(f"\nDebug - First job details: {job_details[0].keys() if job_details else 'No jobs'}")
            elif isinstance(job_details, dict) and job_details:
                first_key = next(iter(job_details))
                print(f"\nDebug - First job details: {job_details[first_key].keys() if job_details else 'No jobs'}")
            else:
                print("\nDebug - No job details available")

            # Convert job_details list to a dictionary keyed by job_id if it's not already a dictionary
            if isinstance(job_details, list):
                job_details_dict = {}
                for job in job_details:
                    job_id = job.get("job_id")
                    if job_id is not None:
                        job_details_dict[job_id] = job

                # Replace job_details list with the dictionary
                job_details = job_details_dict

            # Create job description tuples with proper format
            job_desc_tuples = []

            for job_id, job in job_details.items():
                # Get the job description, falling back to empty string if not found
                job_desc = job.get("job_description", "")
                if not job_desc:
                    # Try alternative keys that might contain the job description
                    for key in ["description", "desc", "text"]:
                        if key in job and job[key]:
                            job_desc = job[key]
                            break

                # Add to tuples if we have a description
                if job_desc:
                    job_desc_tuples.append((job_id, job_desc))
                else:
                    print(f"Warning: No job description found for job ID {job_id}")

            print(f"Found {len(job_desc_tuples)} jobs with descriptions")

            # Process jobs with LLM
            results = batch_process_jobs(resume_skills_text, job_desc_tuples, with_explanations=True)

        elif match_method == "2":
            # TF-IDF matching
            from stages.llm_matcher.llm_job_matcher_optimized import two_stage_job_matching

            logger.info(f"Using TF-IDF matching for {len(job_details)} jobs")
            print(f"\n🔍 Using TF-IDF matching for {len(job_details)} jobs")

            # Print the first job details to debug
            if isinstance(job_details, list) and job_details:
                print(f"\nDebug - First job details: {job_details[0].keys() if job_details else 'No jobs'}")
            elif isinstance(job_details, dict) and job_details:
                first_key = next(iter(job_details))
                print(f"\nDebug - First job details: {job_details[first_key].keys() if job_details else 'No jobs'}")
            else:
                print("\nDebug - No job details available")

            # Convert job_details list to a dictionary keyed by job_id if it's not already a dictionary
            if isinstance(job_details, list):
                job_details_dict = {}
                for job in job_details:
                    job_id = job.get("job_id")
                    if job_id is not None:
                        job_details_dict[job_id] = job

                # Replace job_details list with the dictionary
                job_details = job_details_dict

            # Create job description tuples with proper format
            job_desc_tuples = []
            job_skills_dict = {}

            for job_id, job in job_details.items():
                # Get the job description, falling back to empty string if not found
                job_desc = job.get("job_description", "")
                if not job_desc:
                    # Try alternative keys that might contain the job description
                    for key in ["description", "desc", "text"]:
                        if key in job and job[key]:
                            job_desc = job[key]
                            break

                # Get job skills
                job_skills = job.get("skills", "")

                # Add to tuples if we have a description
                if job_desc:
                    job_desc_tuples.append((job_id, job_desc))
                    job_skills_dict[job_id] = job_skills

                    # Save TF-IDF score to database if available
                    if DATABASE_AVAILABLE and "job_id" in job:
                        try:
                            from database.db_manager import DBManager
                            db = DBManager()
                            scores_to_save = {
                                'score': None,  # Will be set later
                                'tfidf_score': None,  # Will be set after matching
                                'llm_score': None,  # Not using LLM here
                                'normal_score': None  # Not using simple matching here
                            }
                            db.update_job_scores(job["job_id"], scores_to_save)
                        except Exception as e:
                            logger.error(f"Error initializing scores in database: {e}")
                else:
                    print(f"Warning: No job description found for job ID {job.get('job_id', 'unknown')}")

            print(f"Found {len(job_desc_tuples)} jobs with descriptions")

            # Use TF-IDF matching with both job descriptions and skills
            results = two_stage_job_matching(resume_skills_text, job_desc_tuples,
                                           job_skills=job_skills_dict,
                                           threshold=3.0,
                                           with_explanations=True,
                                           skip_llm=True)  # Skip the LLM stage

            # Update database with TF-IDF scores
            if DATABASE_AVAILABLE:
                for job_id, score, explanation in results:
                    try:
                        if job_id in job_details:
                            db_job_id = job_id  # The job_id is already the database job_id
                            scores_to_save = {
                                'score': score,  # Overall score
                                'tfidf_score': score,  # TF-IDF specific score
                                'llm_score': None,  # Not using LLM
                                'normal_score': None  # Not using simple matching
                            }
                            db.update_job_scores(db_job_id, scores_to_save)
                            logger.info(f"Updated TF-IDF scores for job ID {db_job_id}")
                    except Exception as e:
                        logger.error(f"Error updating TF-IDF scores in database: {e}")

        else:
            # Simple keyword matching
            from stages.llm_matcher.llm_job_matcher_optimized import quick_match_score

            logger.info(f"Using simple keyword matching for {len(job_details)} jobs")
            print(f"\n🔍 Using simple keyword matching for {len(job_details)} jobs")

            # Process jobs using simple keyword matching
            # Print the first job details to debug
            if isinstance(job_details, list) and job_details:
                print(f"\nDebug - First job details: {job_details[0].keys() if job_details else 'No jobs'}")
            elif isinstance(job_details, dict) and job_details:
                first_key = next(iter(job_details))
                print(f"\nDebug - First job details: {job_details[first_key].keys() if job_details else 'No jobs'}")
            else:
                print("\nDebug - No job details available")

            # Convert job_details list to a dictionary keyed by job_id if it's not already a dictionary
            if isinstance(job_details, list):
                job_details_dict = {}
                for job in job_details:
                    job_id = job.get("job_id")
                    if job_id is not None:
                        job_details_dict[job_id] = job

                # Replace job_details list with the dictionary
                job_details = job_details_dict

            # Process jobs using simple keyword matching
            results = []
            for job_id, job in job_details.items():
                # Get the job description and skills safely
                job_desc = job.get("job_description", "") or job.get("description", "") or job.get("desc", "") or ""
                job_skills = job.get("skills", [])
                if isinstance(job_skills, list):
                    job_skills = ", ".join(job_skills)

                if job_desc:
                    # Use both job description and skills for matching
                    score = quick_match_score(resume_skills_text, job_desc, job_skills)
                    explanation = f"Matched {score} out of 10 keywords with your resume"
                    results.append((job_id, score, explanation))

                    # Update database scores if available
                    if DATABASE_AVAILABLE and "job_id" in job:
                        try:
                            scores_to_save = {
                                'score': score,
                                'normal_score': score,
                                'llm_score': None,
                                'tfidf_score': None
                            }
                            db.update_job_scores(job["job_id"], scores_to_save)
                        except Exception as e:
                            logger.error(f"Error updating scores in database: {e}")
                else:
                    print(f"Warning: No job description found for job ID {job_id}")

            print(f"Found {len(results)} jobs with descriptions")

            # Create ranked jobs list from results safely
            ranked_jobs = []
            for job_id, score, explanation in results:
                if score is not None and job_id in job_details:
                    job = job_details[job_id]
                    ranked_job = {
                        "title": job.get("role", "Unknown"),
                        "company": job.get("company_name", "Unknown"),
                        "location": job.get("location", "Unknown"),
                        "url": job.get("url", ""),
                        "score": score,
                        "explanation": explanation,
                        "details": job
                    }
                    ranked_jobs.append(ranked_job)
                else:
                    logger.warning(f"Skipping invalid job_id {job_id} or score {score}")

        # Create ranked jobs list
        if match_method == "1" or match_method == "2":
            # For LLM and TF-IDF matching, results are (job_id, score, explanation) tuples
            for job_id, score, explanation in results:
                if score is None:
                    logger.warning(f"No score for job ID: {job_id}")
                    continue

                # Get the job from the job_details dictionary
                if job_id in job_details:
                    job = job_details[job_id]
                    ranked_job = {
                        "title": job.get("role", "Unknown"),
                        "company": job.get("company_name", "Unknown"),
                        "location": job.get("location", "Unknown"),
                        "url": job.get("url", ""),
                        "score": score,
                        "explanation": explanation,
                        "details": job
                    }
                    ranked_jobs.append(ranked_job)
                else:
                    logger.warning(f"Job ID {job_id} not found in job_details dictionary")
        else:
            # For simple keyword matching, results are (job_id, score, explanation) tuples
            for job_id, score, explanation in results:
                if score is None:
                    logger.warning(f"No score for job ID: {job_id}")
                    continue

                # Get the job from the job_details dictionary
                if job_id in job_details:
                    job = job_details[job_id]
                    ranked_job = {
                        "title": job.get("role", "Unknown"),
                        "company": job.get("company_name", "Unknown"),
                        "location": job.get("location", "Unknown"),
                        "url": job.get("url", ""),
                        "score": score,
                        "explanation": explanation,
                        "details": job
                    }
                    ranked_jobs.append(ranked_job)
                else:
                    logger.warning(f"Job ID {job_id} not found in job_details dictionary")

        # First, filter out "Apply on company site" jobs if requested
        print("\n🔍 Do you want to filter out 'Apply on company site' jobs?")
        filter_company_site = input("Filter out 'Apply on company site' jobs? (y/n): ").strip().lower() == 'y'

        if filter_company_site:
            original_count = len(ranked_jobs)
            ranked_jobs = [job for job in ranked_jobs if job.get("details", {}).get("apply_type", "") != "company_site"]
            filtered_count = original_count - len(ranked_jobs)
            print(f"\n✅ Filtered out {filtered_count} 'Apply on company site' jobs")

        # Prioritize jobs that match user-selected roles
        if user_roles:
            for job in ranked_jobs:
                # Check if job role contains any of the user-selected roles
                job_role = job.get("title", "").lower()
                role_match = False
                role_match_score = 0

                for role in user_roles:
                    if role.lower() in job_role:
                        role_match = True
                        role_match_score += 1

                # Add a role match bonus to the score (up to 2 points)
                if role_match:
                    original_score = job["score"]
                    # Add bonus based on how many roles matched (max 2 points)
                    bonus = min(role_match_score, 2)
                    job["score"] = min(original_score + bonus, 10)  # Cap at 10
                    job["explanation"] = f"Role match bonus: +{bonus}. " + job.get("explanation", "")
                    print(f"\n✅ Added role match bonus to job: {job['title']}")
                    print(f"  Original score: {original_score}, New score: {job['score']}")

        # Sort by score (descending)
        ranked_jobs.sort(key=lambda x: x["score"], reverse=True)

        # Save ranked jobs to file only if database is not available
        if not DATABASE_AVAILABLE:
            ranked_file = os.path.join(output_dir, "ranked_jobs.json")
            save_json(ranked_jobs, ranked_file)
            logger.info(f"Ranked jobs saved to {ranked_file}")
        else:
            # Scores are now updated within the matching functions
            logger.info("Ranked jobs processed. Scores updated during matching.")

        # Apply our enhanced eligibility criteria
        print("\n🔍 Applying enhanced eligibility criteria...")
        eligible_jobs = []
        ineligible_jobs = []

        # Initialize skills variable if it doesn't exist
        if 'skills' not in locals():
            skills = []

        # Get search skills from resume data or user input
        search_skills = []
        if resume_data and "search_skills" in resume_data:
            search_skills = resume_data["search_skills"]
        elif skills:
            search_skills = skills

        print(f"\n🔍 Using {len(search_skills)} search skills for job matching: {', '.join(search_skills)}")

        for job in ranked_jobs:
            # Check if job meets our enhanced eligibility criteria
            is_eligible, reason = check_job_eligibility(job, user_roles, min_score=5.0, search_skills=search_skills)

            if is_eligible:
                eligible_jobs.append(job)
                print(f"\n✅ Eligible: {job['title']} at {job['company']}")
                print(f"  Score: {job['score']}, Reason: {reason}")
                # Add the eligibility reason to the job
                job["eligibility_reason"] = reason
            else:
                ineligible_jobs.append(job)
                print(f"\n❌ Not eligible: {job['title']} at {job['company']}")
                print(f"  Score: {job['score']}, Reason: {reason}")

        # Use eligible jobs for further processing
        filtered_jobs = eligible_jobs
        logger.info(f"Found {len(filtered_jobs)} eligible jobs based on enhanced criteria")

        # Display ranked jobs
        print("\n📊 Ranked Jobs:")
        if eligible_jobs:
            print(f"Found {len(eligible_jobs)} eligible jobs based on enhanced criteria")
            for i, job in enumerate(eligible_jobs[:10], 1):
                print(f"{i}. {job['title']} at {job['company']}")
                print(f"   Overall Score: {job['score']}/10")
                if job.get('llm_score'):
                    print(f"   LLM Score: {job['llm_score']}/10")
                if job.get('tfidf_score'):
                    print(f"   TF-IDF Score: {job['tfidf_score']}/10")
                if job.get('normal_score'):
                    print(f"   Keyword Score: {job['normal_score']}/10")
                print(f"   Explanation: {job['explanation']}")
                print(f"   Eligibility: {job.get('eligibility_reason', 'Unknown')}")
                print()
        else:
            print("No jobs met the eligibility criteria. Here are the top ranked jobs:")
            for i, job in enumerate(ranked_jobs[:5], 1):
                print(f"{i}. {job['title']} at {job['company']}")
                print(f"   Overall Score: {job['score']}/10")
                if job.get('llm_score'):
                    print(f"   LLM Score: {job['llm_score']}/10")
                if job.get('tfidf_score'):
                    print(f"   TF-IDF Score: {job['tfidf_score']}/10")
                if job.get('normal_score'):
                    print(f"   Keyword Score: {job['normal_score']}/10")
                print(f"   Explanation: {job['explanation']}")
                print()

        ranked_jobs = filtered_jobs

        if not ranked_jobs:
            logger.error("No jobs matched the minimum score")
            return 1
    else:
        # Try to load ranked jobs from file
        ranked_data = load_json(os.path.join(output_dir, "ranked_jobs.json"))
        if ranked_data:
            # Filter by minimum score
            ranked_jobs = [job for job in ranked_data if job["score"] >= args.min_score]
            logger.info(f"Loaded {len(ranked_jobs)} ranked jobs from file")

    # Apply to jobs if in full, apply, or match mode with --apply flag
    if (args.mode in ['full', 'apply', 'match'] and (args.apply or args.auto_apply)) and ranked_jobs:
        # Start browser
        if not job_applier.start_browser():
            logger.error("Failed to start browser")
            return 1

        try:
            # Check if auto-apply is enabled
            if args.auto_apply:
                # Filter jobs for direct apply
                direct_apply_jobs = [job for job in ranked_jobs
                                   if job.get("details", {}).get("apply_type", "") in ["naukri", "direct"]]

                if direct_apply_jobs:
                    print(f"\n🔍 Auto-applying to {len(direct_apply_jobs)} eligible jobs...")

                    # Load user data
                    user_data_file = os.path.join(output_dir, "user_data.json")
                    user_data = load_json(user_data_file)

                    if not user_data:
                        # Collect user data if not found
                        print("\n📋 No user data found. Let's collect it now...")
                        user_data = collect_user_data(resume_path=args.resume, email=args.email)

                        if user_data:
                            # Save the newly collected user data
                            save_json(user_data, user_data_file)
                            logger.info(f"Saved new user data to {user_data_file}")

                    # Apply to all jobs using test_naukri_chatbot.py
                    results = apply_to_multiple_jobs(
                        job_queue=direct_apply_jobs,
                        chrome_profile_path=profile_path,
                        user_data=user_data,
                        output_dir=output_dir
                    )

                    # Process results
                    if results:
                        # Check if results is a list (expected format)
                        if isinstance(results, list):
                            # Extract applied and failed jobs
                            applied_jobs = [job for job in results if job.get("applied", False)]
                            failed_jobs = [job for job in results if not job.get("applied", False)]
                            skipped_jobs = []
                        else:
                            # If results is not a list, assume all jobs failed
                            logger.warning("Results is not a list. Assuming all jobs failed.")
                            applied_jobs = []
                            failed_jobs = direct_apply_jobs
                            skipped_jobs = []
                    else:
                        # If no results, assume all jobs failed
                        applied_jobs = []
                        failed_jobs = direct_apply_jobs
                        skipped_jobs = []

                    # Skip the regular application process
                    logger.info(f"Auto-applied to {len(applied_jobs)} jobs, {len(failed_jobs)} failed")
                else:
                    print("\n⚠️ No jobs eligible for direct application found")
                    applied_jobs = []
                    failed_jobs = []
                    skipped_jobs = ranked_jobs
            else:
                # Regular application process
                # Create a new page
                page = job_applier.context.new_page()

                # Navigate to Naukri
                page.goto("https://www.naukri.com")

                # Ensure logged in
                if not job_applier.ensure_logged_in(page, "naukri"):
                    logger.error("Failed to log in to Naukri")
                    return 1

                # Apply to each job
                applied_jobs = []
                failed_jobs = []
                skipped_jobs = []

                # Apply to each job individually
                for i, job in enumerate(ranked_jobs):
                    job_url = job["url"]
                    apply_type = job.get("details", {}).get("apply_type", "unknown")

                    # Jobs have already been filtered by eligibility criteria
                    # We can directly proceed to application

                    logger.info(f"Applying to job {i+1}/{len(ranked_jobs)}: {job['title']} (Score: {job['score']}, Apply type: {apply_type})")
                    print(f"\n🔍 Applying to job {i+1}/{len(ranked_jobs)}: {job['title']}")
                    print(f"  Score: {job['score']}, Apply type: {apply_type}")

                    try:
                        if args.apply:
                            # Actually apply to the job
                            success = False

                            # Get the apply type
                            apply_type = job.get("details", {}).get("apply_type", "unknown")

                            # Display job details before applying
                            print(f"\n🔍 Applying to job {i+1}/{len(ranked_jobs)}: {job.get('title', 'Unknown')}")
                            print(f"  Score: {job.get('score', 0)}, Apply type: {apply_type}")
                            print(f"  URL: {job_url}")

                            # Load user data from the collected user data
                            user_data_file = os.path.join(output_dir, "user_data.json")
                            user_data = load_json(user_data_file)

                            if not user_data:
                                # Collect user data if not found
                                print("\n📋 No user data found. Let's collect it now...")
                                user_data = collect_user_data(resume_path=args.resume, email=args.email)

                                if user_data:
                                    # Save the newly collected user data
                                    save_json(user_data, user_data_file)
                                    logger.info(f"Saved new user data to {user_data_file}")

                            # Call run_naukri_chatbot.py as a separate process
                            print(f"\n🔍 Starting chatbot interaction test...")

                            # Save user data to a temporary file for the subprocess to use
                            # (This is still needed because the subprocess needs to read the file)
                            temp_user_data_file = os.path.join(output_dir, "temp_user_data.json")
                            with open(temp_user_data_file, 'w', encoding='utf-8') as f:
                                json.dump(user_data, f, indent=2, ensure_ascii=False)
                            logger.info(f"Temporary user data saved to {temp_user_data_file}")

                            # Construct the command to run run_naukri_chatbot.py as a separate process
                            cmd = [
                                sys.executable,  # Python executable
                                os.path.join(current_dir, "run_naukri_chatbot.py"),
                                "--job-url", job_url,
                                "--profile-path", profile_path,
                                "--user-data-file", temp_user_data_file
                            ]

                            # Run the command and capture the output
                            import subprocess
                            process = subprocess.run(cmd, capture_output=True, text=True)

                            # Print the output
                            print(process.stdout)

                            # Check if the process was successful
                            success = process.returncode == 0

                            # Try to parse the result from the output
                            apply_method = None
                            if "using chatbot" in process.stdout:
                                apply_method = "chatbot"
                            elif "using direct" in process.stdout:
                                apply_method = "direct"
                            elif "already applied" in process.stdout:
                                apply_method = "already_applied"

                            # Store the application method in the job details
                            if apply_method:
                                if "details" not in job:
                                    job["details"] = {}
                                job["details"]["application_method"] = apply_method

                            if success:
                                method_str = f" using {apply_method}" if apply_method else ""
                                print(f"\n✅ Successfully interacted with the Naukri chatbot{method_str}!")
                                logger.info(f"Successfully applied to job: {job['title']} using {apply_method if apply_method else 'unknown method'}")
                                applied_jobs.append(job)

                                # Update job status in database if available
                                if DATABASE_AVAILABLE and user_id and "job_id" in job:
                                    # Update job status
                                    update_job_status(job["job_id"], "applied")

                                    # Save application record
                                    save_job_application(
                                        job_id=job["job_id"],
                                        user_id=user_id,
                                        status="success",
                                        apply_method=apply_method
                                    )
                                    logger.info(f"Updated job status and saved application record in database for job ID: {job['job_id']}")
                            else:
                                print(f"\n❌ Failed to interact with the Naukri chatbot.")
                                logger.warning(f"Failed to apply to job: {job['title']}")
                                failed_jobs.append(job)

                                # Update job status in database if available
                                if DATABASE_AVAILABLE and user_id and "job_id" in job:
                                    # Update job status
                                    update_job_status(job["job_id"], "failed")

                                    # Save application record
                                    save_job_application(
                                        job_id=job["job_id"],
                                        user_id=user_id,
                                        status="failed",
                                        apply_method=apply_method,
                                        error_message="Application failed"
                                    )
                                    logger.info(f"Updated job status and saved application record in database for job ID: {job['job_id']}")
                        else:
                            # Just simulate application
                            logger.info(f"Simulated application to job: {job['title']}")
                            applied_jobs.append(job)

                        # Wait a bit between applications to simulate human behavior
                        wait_time = random.randint(5, 10)
                        print(f"\nWaiting {wait_time} seconds before next application...")
                        time.sleep(wait_time)

                    except Exception as e:
                        logger.error(f"Error applying to job {job_url}: {e}")
                        failed_jobs.append(job)

            # Save application results to file only if database is not available
            results = {
                "applied": applied_jobs,
                "failed": failed_jobs
            }

            if not DATABASE_AVAILABLE:
                results_file = os.path.join(output_dir, "application_results.json")
                save_json(results, results_file)
                logger.info(f"Application results saved to {results_file}")
            else:
                logger.info("Application results saved to database")

            # Generate report
            logger.info("Generating report")

            # Create report
            report = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "applied_count": len(applied_jobs),
                "failed_count": len(failed_jobs),
                "skipped_count": len(skipped_jobs),
                "applied_jobs": [
                    {
                        "title": job["title"],
                        "company": job["company"],
                        "location": job["location"],
                        "score": job["score"],
                        "url": job["url"],
                        "apply_type": job.get("details", {}).get("apply_type", "unknown"),
                        "application_method": job.get("details", {}).get("application_method", "unknown")
                    }
                    for job in applied_jobs
                ],
                "failed_jobs": [
                    {
                        "title": job["title"],
                        "company": job["company"],
                        "location": job["location"],
                        "score": job["score"],
                        "url": job["url"],
                        "apply_type": job.get("details", {}).get("apply_type", "unknown"),
                        "application_method": job.get("details", {}).get("application_method", "unknown")
                    }
                    for job in failed_jobs
                ],
                "skipped_jobs": [
                    {
                        "title": job["title"],
                        "company": job["company"],
                        "location": job["location"],
                        "score": job["score"],
                        "url": job["url"],
                        "apply_type": job.get("details", {}).get("apply_type", "unknown"),
                        "application_method": job.get("details", {}).get("application_method", "unknown")
                    }
                    for job in skipped_jobs
                ]
            }

            # Save report to file (always save for reference)
            report_file = os.path.join(output_dir, "report.json")
            save_json(report, report_file)
            logger.info(f"Report saved to {report_file}")

            # Print report summary
            print("\n📊 Application Report:")
            print(f"Applied: {report['applied_count']} jobs")
            print(f"Failed: {report['failed_count']} jobs")
            print(f"Skipped: {report['skipped_count']} jobs")

            # Get application statistics from database if available
            if DATABASE_AVAILABLE and user_id:
                stats = get_application_stats(user_id)
                if stats:
                    print("\n📊 Database Application Statistics:")
                    print(f"Total Applications: {stats.get('total_applications', 0)}")
                    print(f"Successful Applications: {stats.get('successful_applications', 0)}")
                    print(f"Failed Applications: {stats.get('failed_applications', 0)}")
                    print(f"Skipped Applications: {stats.get('skipped_applications', 0)}")

            if report["applied_count"] > 0:
                print("\nApplied Jobs:")
                for i, job in enumerate(report["applied_jobs"], 1):
                    method_str = f", Method: {job['application_method']}" if job['application_method'] != "unknown" else ""
                    print(f"{i}. {job['title']} at {job['company']} (Score: {job['score']}, Apply type: {job['apply_type']}{method_str})")

            if report["skipped_count"] > 0:
                print("\nSkipped Jobs:")
                for i, job in enumerate(report["skipped_jobs"], 1):
                    method_str = f", Method: {job['application_method']}" if job['application_method'] != "unknown" else ""
                    print(f"{i}. {job['title']} at {job['company']} (Score: {job['score']}, Apply type: {job['apply_type']}{method_str})")

            print(f"\nReport saved to {report_file}")

        finally:
            # Close the browser
            job_applier.close_browser()

    logger.info("Workflow completed successfully")
    return 0

if __name__ == "__main__":
    sys.exit(main())
