"""Seed the admin-managed email template library used by Lead Sale."""

import frappe

SYSTEM_TEMPLATES = (
	{
		"template_name": "Liên hệ lần đầu",
		"library_category": "first-touch",
		"description": "Mở đầu cuộc trò chuyện với học sinh mới.",
		"subject": "Chào {{student.first_name}}, anh/chị là tư vấn viên từ {{school.name}}",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Anh/chị là {{owner.full_name}}, tư vấn viên tuyển sinh từ {{school.name}}.\n"
			"Anh/chị liên hệ để hỗ trợ em tìm hiểu thêm về chương trình đào tạo, ngành học, "
			"học phí và các thông tin tuyển sinh phù hợp với nhu cầu của em.\n"
			"Nếu thuận tiện, em có thể phản hồi lại tin nhắn này hoặc cho anh/chị biết thời gian "
			"phù hợp để trao đổi nhé.\n\n"
			"Trân trọng,\n{{owner.full_name}}\n{{owner.phone}}"
		),
	},
	{
		"template_name": "Lead từ sự kiện / form / nội dung",
		"library_category": "first-touch",
		"description": "Tiếp cận lead sau khi để lại thông tin.",
		"subject": "Chào {{student.first_name}}, cảm ơn em đã quan tâm đến {{school.name}}",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Anh/chị thấy em đã để lại thông tin qua {{lead.source}} của {{school.name}}.\n"
			"Anh/chị gửi em thêm một số thông tin về chương trình tuyển sinh mà em đang quan tâm.\n"
			"Nếu em có câu hỏi hoặc muốn được tư vấn thêm, em cứ phản hồi lại tin nhắn này nhé.\n\n"
			"Trân trọng,\n{{owner.full_name}}\n{{owner.phone}}"
		),
	},
	{
		"template_name": "Giới thiệu chương trình phù hợp",
		"library_category": "first-touch",
		"description": "Gợi ý chương trình theo nhu cầu của học sinh.",
		"subject": "Chương trình {{program.name}} có thể phù hợp với em",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Dựa trên thông tin em đang quan tâm, anh/chị muốn giới thiệu đến em chương trình "
			"{{program.name}} tại {{school.name}}.\n"
			"Chương trình này phù hợp với những bạn quan tâm đến {{program.interest_area}} và "
			"mong muốn phát triển theo hướng {{program.career_direction}}.\n"
			"Em có thể xem thêm tại: {{program.link}}\n"
			"Nếu em muốn, anh/chị có thể tư vấn thêm để xem chương trình này có phù hợp với "
			"định hướng của em không."
		),
	},
	{
		"template_name": "Không bắt máy",
		"library_category": "follow-up",
		"description": "Gửi lại thông tin sau khi chưa kết nối được.",
		"subject": "Anh/chị vừa liên hệ với em",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Anh/chị vừa liên hệ với em để trao đổi một số thông tin về tuyển sinh tại "
			"{{school.name}}, nhưng chưa kết nối được với em.\n"
			"Khi thuận tiện, em có thể phản hồi lại tin nhắn này hoặc liên hệ với anh/chị qua số "
			"{{owner.phone}}.\n"
			"Anh/chị rất sẵn sàng hỗ trợ em.\n\n"
			"Trân trọng,\n{{owner.full_name}}"
		),
	},
	{
		"template_name": "Follow-up sau tư vấn",
		"library_category": "follow-up",
		"description": "Tóm tắt và nhắc lại thông tin sau buổi tư vấn.",
		"subject": "Thông tin sau buổi tư vấn tại {{school.name}}",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Cảm ơn em đã dành thời gian trao đổi cùng anh/chị.\n"
			"Dựa trên nội dung mình vừa trao đổi, em đang quan tâm đến {{program.name}} và muốn "
			"tìm hiểu thêm về lộ trình học, học phí cũng như cơ hội học bổng.\n"
			"Anh/chị gửi lại thông tin để em tiện tham khảo.\n"
			"Nếu em còn câu hỏi nào khác, cứ phản hồi lại tin nhắn này nhé.\n\n"
			"Trân trọng,\n{{owner.full_name}}"
		),
	},
	{
		"template_name": "Tiếp tục cuộc trò chuyện",
		"library_category": "follow-up",
		"description": "Mở lại cuộc trao đổi chưa đi sâu vào nhu cầu.",
		"subject": "Anh/chị muốn trao đổi thêm với em",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Trong lần trao đổi trước, mình chưa có nhiều thời gian để tìm hiểu kỹ về nhu cầu và "
			"định hướng của em.\n"
			"Anh/chị muốn trao đổi thêm để hỗ trợ em tốt hơn về ngành học, học phí, học bổng và "
			"kế hoạch tuyển sinh.\n"
			"Khi thuận tiện, em có thể phản hồi lại tin nhắn này nhé."
		),
	},
	{
		"template_name": "Xác nhận bước tiếp theo",
		"library_category": "follow-up",
		"description": "Xác nhận hành động tiếp theo trong quy trình.",
		"subject": "Bước tiếp theo của em tại {{school.name}}",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Dựa trên thông tin hiện tại, bước tiếp theo em cần thực hiện là:\n"
			"{{application.next_step}}\n"
			"Em có thể thực hiện tại: {{application.link}}\n"
			"Nếu cần hỗ trợ trong quá trình thực hiện, anh/chị sẽ đồng hành cùng em."
		),
	},
	{
		"template_name": "Nhắc phản hồi",
		"library_category": "follow-up",
		"description": "Nhắc nhẹ học sinh phản hồi thông tin đã nhận.",
		"subject": "Em đã xem thông tin anh/chị gửi chưa?",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Anh/chị muốn hỏi em đã có thời gian xem những thông tin về "
			"{{student.interested_program}} mà anh/chị gửi trước đó chưa.\n"
			"Nếu em vẫn đang cân nhắc hoặc còn câu hỏi về chương trình học, học phí, học bổng "
			"hay hồ sơ tuyển sinh, anh/chị rất sẵn sàng hỗ trợ.\n"
			"Em cứ phản hồi lại khi thuận tiện nhé."
		),
	},
	{
		"template_name": "Thông tin ngành / chương trình",
		"library_category": "admission-consultation",
		"description": "Gửi thông tin tổng quan về chương trình học.",
		"subject": "Thông tin về {{program.name}}",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Theo nội dung em đang quan tâm, anh/chị gửi em một số thông tin về chương trình "
			"{{program.name}} tại {{school.name}}.\n"
			"Em có thể tìm hiểu thêm về:\n"
			"- Nội dung chương trình học\n"
			"- Thời gian đào tạo\n"
			"- Cơ hội nghề nghiệp\n"
			"- Học phí\n"
			"- Điều kiện tuyển sinh\n\n"
			"Thông tin chi tiết: {{program.link}}\n"
			"Nếu em muốn được tư vấn kỹ hơn về chương trình này, anh/chị có thể hỗ trợ thêm."
		),
	},
	{
		"template_name": "Học phí & học bổng",
		"library_category": "admission-consultation",
		"description": "Giới thiệu học phí và các chính sách học bổng.",
		"subject": "Thông tin học phí và học bổng tại {{school.name}}",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Anh/chị gửi em thông tin về học phí và các chương trình học bổng hiện đang áp dụng "
			"tại {{school.name}}.\n"
			"Học phí tham khảo: {{tuition.amount}}\n"
			"Chương trình học bổng: {{scholarship.name}}\n"
			"Thông tin chi tiết: {{scholarship.link}}\n"
			"Tùy theo hồ sơ và kết quả xét tuyển, em có thể đủ điều kiện nhận các mức hỗ trợ "
			"khác nhau.\n"
			"Nếu em muốn kiểm tra điều kiện học bổng của mình, anh/chị có thể hỗ trợ."
		),
	},
	{
		"template_name": "Mời Open Day / sự kiện",
		"library_category": "admission-consultation",
		"description": "Mời học sinh tham gia sự kiện tuyển sinh.",
		"subject": "Mời {{student.first_name}} tham gia {{event.name}}",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"{{school.name}} sắp tổ chức chương trình {{event.name}} dành cho các bạn học sinh "
			"đang quan tâm đến môi trường học tập và chương trình tuyển sinh.\n"
			"Thời gian: {{event.datetime}}\n"
			"Địa điểm: {{event.location}}\n"
			"Đăng ký tham gia tại: {{event.registration_link}}\n\n"
			"Đây là dịp để em trực tiếp tìm hiểu về chương trình học, trải nghiệm môi trường và "
			"trao đổi với đội ngũ tư vấn.\n"
			"Rất mong được gặp em tại sự kiện!"
		),
	},
	{
		"template_name": "Xác nhận lịch tư vấn",
		"library_category": "admission-consultation",
		"description": "Xác nhận thời gian và hình thức tư vấn.",
		"subject": "Xác nhận lịch tư vấn của {{student.first_name}}",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Anh/chị xác nhận lịch tư vấn của em như sau:\n"
			"Thời gian: {{appointment.datetime}}\n"
			"Hình thức: {{appointment.type}}\n"
			"Địa điểm/Link: {{appointment.location}}\n\n"
			"Nếu em cần thay đổi thời gian, hãy phản hồi lại tin nhắn này để anh/chị hỗ trợ.\n"
			"Hẹn gặp em!\n{{owner.full_name}}\n{{owner.phone}}"
		),
	},
	{
		"template_name": "Nhắc hoàn thiện hồ sơ",
		"library_category": "application-conversion",
		"description": "Nhắc bổ sung thông tin còn thiếu trong hồ sơ.",
		"subject": "Hồ sơ tuyển sinh của em cần bổ sung thông tin",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Anh/chị kiểm tra hồ sơ tuyển sinh của em và hiện vẫn còn một số thông tin cần bổ sung.\n"
			"Thông tin cần hoàn thiện:\n"
			"{{application.missing_documents}}\n"
			"Em có thể hoàn thiện hồ sơ tại: {{application.link}}\n"
			"Nếu gặp khó khăn trong quá trình bổ sung hồ sơ, hãy phản hồi lại tin nhắn này để "
			"anh/chị hỗ trợ.\n\n"
			"Trân trọng,\n{{owner.full_name}}"
		),
	},
	{
		"template_name": "Xác nhận đã nhận hồ sơ",
		"library_category": "application-conversion",
		"description": "Thông báo hồ sơ đã được tiếp nhận.",
		"subject": "{{school.name}} đã nhận được thông tin của em",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"{{school.name}} đã nhận được thông tin đăng ký của em.\n"
			"Trạng thái hiện tại: {{application.status}}\n"
			"Bước tiếp theo: {{application.next_step}}\n"
			"Anh/chị sẽ tiếp tục cập nhật cho em khi có thông tin mới.\n"
			"Cảm ơn em đã quan tâm đến {{school.name}}."
		),
	},
	{
		"template_name": "Đủ điều kiện / Qualified",
		"library_category": "application-conversion",
		"description": "Thông báo kết quả phù hợp và hướng xử lý tiếp theo.",
		"subject": "Cập nhật kết quả tư vấn tuyển sinh của em",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Dựa trên thông tin hiện tại, em đang phù hợp với chương trình {{program.name}} tại "
			"{{school.name}}.\n"
			"Bước tiếp theo em cần thực hiện là: {{application.next_step}}\n"
			"Em có thể tiếp tục tại: {{application.link}}\n"
			"Nếu cần hỗ trợ trong quá trình thực hiện, anh/chị sẽ đồng hành cùng em."
		),
	},
	{
		"template_name": "Hướng dẫn bước tiếp theo",
		"library_category": "application-conversion",
		"description": "Hướng dẫn học sinh hoàn tất bước tiếp theo.",
		"subject": "Hướng dẫn bước tiếp theo trong hồ sơ của em",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Để tiếp tục quy trình tuyển sinh tại {{school.name}}, em vui lòng thực hiện bước sau:\n"
			"{{application.next_step}}\n"
			"Em có thể bắt đầu tại: {{application.link}}\n"
			"Nếu cần hỗ trợ, em cứ phản hồi lại tin nhắn này nhé."
		),
	},
	{
		"template_name": "Lâu chưa phản hồi",
		"library_category": "re-engagement",
		"description": "Khơi lại cuộc trò chuyện sau một thời gian im lặng.",
		"subject": "Anh/chị muốn hỏi thăm em một chút",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Đã một thời gian rồi anh/chị chưa nhận được phản hồi từ em.\n"
			"Anh/chị muốn hỏi thăm xem em còn cần thêm thông tin về chương trình, học phí hoặc "
			"học bổng không.\n"
			"Nếu em vẫn đang tìm hiểu, em cứ phản hồi khi thuận tiện nhé."
		),
	},
	{
		"template_name": "Tái kết nối",
		"library_category": "re-engagement",
		"description": "Kết nối lại với học sinh từng quan tâm.",
		"subject": "Em vẫn còn quan tâm đến {{school.name}} chứ?",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Một thời gian rồi anh/chị chưa có dịp trao đổi lại với em.\n"
			"Anh/chị muốn hỏi hiện tại em có còn quan tâm đến chương trình tuyển sinh tại "
			"{{school.name}} không.\n"
			"Nếu em vẫn đang tìm hiểu, anh/chị có thể cập nhật cho em những thông tin mới nhất về "
			"ngành học, học phí, học bổng và các mốc tuyển sinh sắp tới.\n"
			"Nếu em không còn nhu cầu, em cũng có thể cho anh/chị biết để anh/chị cập nhật thông tin "
			"nhé."
		),
	},
	{
		"template_name": "Close-loop / xác nhận không còn nhu cầu",
		"library_category": "re-engagement",
		"description": "Khép lại việc liên hệ một cách lịch sự.",
		"subject": "Xác nhận nhu cầu tư vấn tuyển sinh",
		"body": (
			"Chào {{student.first_name}},\n\n"
			"Anh/chị đã liên hệ với em một vài lần nhưng chưa nhận được phản hồi.\n"
			"Anh/chị muốn xác nhận xem em có còn nhu cầu tìm hiểu chương trình tại {{school.name}} "
			"hay không.\n"
			"Nếu em vẫn quan tâm, chỉ cần phản hồi lại tin nhắn này, anh/chị sẽ tiếp tục hỗ trợ.\n"
			"Nếu hiện tại em chưa có nhu cầu, anh/chị sẽ tạm dừng liên hệ để tránh làm phiền em."
		),
	},
)


def execute():
	for template in SYSTEM_TEMPLATES:
		if frappe.db.exists("CRM Message Template Library", {"template_name": template["template_name"]}):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Message Template Library",
				"naming_series": "MSG-LIB-.###",
				"owner": "Administrator",
				"template_name": template["template_name"],
				"category": template["library_category"],
				"description": template["description"],
				"subject": template["subject"],
				"body": template["body"],
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
