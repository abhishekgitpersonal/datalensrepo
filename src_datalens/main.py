from src.snowflake.connector import SnowflakeConnector
from src.salesforce.loader import SalesforceLoader
from src.config.config_template import (
    SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_ACCOUNT, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA,
    SALESFORCE_CLIENT_ID, SALESFORCE_USER, SALESFORCE_PRIVATE_KEY
)

def main():
    # Initialize Snowflake Connector
    snowflake = SnowflakeConnector(
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        account=SNOWFLAKE_ACCOUNT,
        warehouse=SNOWFLAKE_WAREHOUSE,
        database=SNOWFLAKE_DATABASE,
        schema=SNOWFLAKE_SCHEMA
    )

    # Example: Fetch data from Snowflake
    snowflake_query = "SELECT * FROM MY_TABLE;"
    data_fetched = snowflake.fetch_data(snowflake_query)
    print("Data Fetched from Snowflake:", data_fetched)

    # Initialize Salesforce Loader
    salesforce = SalesforceLoader(
        client_id=SALESFORCE_CLIENT_ID,
        user=SALESFORCE_USER,
        private_key=SALESFORCE_PRIVATE_KEY
    )

    # Example: Load data to Salesforce
    salesforce_sobject = "My_Custom_Object__c"
    for row in data_fetched:
        payload = {
            "Field1__c": row[0],
            "Field2__c": row[1]
        }
        response = salesforce.load_data(salesforce_sobject, payload)
        print("Salesforce Response:", response)

if __name__ == "__main__":
    main()