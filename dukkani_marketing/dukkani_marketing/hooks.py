app_name = "dukkani_marketing"
app_title = "Dukani Marketing"
app_publisher = "Dukani"
app_description = "Marketing and customer-service workflows for Dukani"
app_email = "support@dukani.ai"
app_license = "AGPL-3.0-or-later"

required_apps = ["frappe"]

after_install = "dukkani_marketing.install.after_install"

doctype_js = {
    "Dukani Marketing Content": "public/js/marketing_content.js",
}
