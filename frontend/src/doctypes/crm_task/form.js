export class CRMTask {
  onRender() {
    if (this.doc.reference_doctype && this.doc.reference_docname) {
      let label = this.doc.reference_doctype.replace('CRM ', '')

      this.actions = [
        {
          name: 'Redirect Action',
          label: __('Open {0}', [label]),
          onClick: (close) => {
            if (!this.doc.reference_docname) return
            const routeMap = {
              'CRM Contact': { name: 'CRM Contact', params: { crmContactId: this.doc.reference_docname } },
              'CRM Student': { name: 'CRM Student', params: { crmStudentId: this.doc.reference_docname } },
            }
            const route = routeMap[this.doc.reference_doctype]
            if (route) this.router.push(route)
            close?.()
          },
        },
      ]
    }
  }
}
