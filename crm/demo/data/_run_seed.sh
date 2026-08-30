#!/bin/bash
cd /home/frappe/frappe-bench
bench --site crm.localhost reinstall --yes --admin-password admin --mariadb-root-password 123 > /tmp/reinstall.txt 2>&1
echo "REINSTALL_EXIT=$?"
bench --site crm.localhost migrate > /tmp/migrate.txt 2>&1
echo "MIGRATE_EXIT=$?"
echo "=== CONTRACT TESTS ==="
bench --site crm.localhost run-tests --app crm --module crm.demo.test_seed_showcase 2>&1 | tail -6
bench --site crm.localhost execute crm.demo.seed_showcase.ensure_local_integrity_keys
bench --site crm.localhost execute crm.demo.seed_showcase.execute > /tmp/seed_out.json 2> /tmp/seed_err.txt
echo "SEED_EXIT=$?"
tail -15 /tmp/seed_err.txt
echo "=== school_domain ==="
grep -aoE "school_domain[^]]*persons[^,]*" /tmp/seed_out.json | head
grep -aoE "student_errors[^]]*]" /tmp/seed_out.json | head -1
echo "=== VERIFY ==="
bench --site crm.localhost execute crm.demo.seed_showcase.verify 2>&1 | grep -aE "covered_fields|fields_with_gaps|\"ok\"" | head
echo "=== IDEMPOTENT RE-RUN ==="
bench --site crm.localhost execute crm.demo.seed_showcase.execute 2>&1 | grep -aoE "student_errors[^]]*]" | head -1
bench --site crm.localhost execute crm.demo.seed_showcase.verify 2>&1 | grep -aE "\"ok\"" | head -1
echo "=== KA schools ==="
bench --site crm.localhost execute frappe.client.get_list --kwargs "{'doctype':'CRM High School','filters':{'key_account_tier':['!=','']},'fields':['school_name','school_area','key_account_tier','key_account_status','is_key_account'],'limit_page_length':0}" 2>&1 | tail -20
