from briefify.mcp.telemetry_mcp import query_account_usage

# Direct execution test for Acme Corp (Upsell Case)
print("--- Testing Acme Corp ---")
acme_res = query_account_usage("Acme Corp")
print(acme_res)

# Direct execution test for Beta Logistics (Churn Case)
print("\n--- Testing Beta Logistics ---")
beta_res = query_account_usage("Beta Logistics")
print(beta_res)