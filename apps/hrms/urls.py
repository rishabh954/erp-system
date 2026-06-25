from django.urls import path
from .views import (
    EmployeeListView, EmployeeDetailView, EmployeeCreateView, EmployeeUpdateView,
    AttendanceView, CheckInView, CheckOutView,
    LeaveListView, LeaveRequestCreateView, LeaveApproveView,
    PayrollListView, PayrollDetailView, PayrollProcessView,
)
app_name = 'hrms'
urlpatterns = [
    path('employees/', EmployeeListView.as_view(), name='employees'),
    path('employees/create/', EmployeeCreateView.as_view(), name='employee_create'),
    path('employees/<uuid:pk>/', EmployeeDetailView.as_view(), name='employee_detail'),
    path('employees/<uuid:pk>/update/', EmployeeUpdateView.as_view(), name='employee_update'),
    path('attendance/', AttendanceView.as_view(), name='attendance'),
    path('attendance/check-in/', CheckInView.as_view(), name='check_in'),
    path('attendance/check-out/', CheckOutView.as_view(), name='check_out'),
    path('leaves/', LeaveListView.as_view(), name='leaves'),
    path('leaves/create/', LeaveRequestCreateView.as_view(), name='leave_request_create'),
    path('leaves/<uuid:pk>/approve/', LeaveApproveView.as_view(), name='leave_approve'),
    path('payroll/', PayrollListView.as_view(), name='payroll'),
    path('payroll/<uuid:pk>/', PayrollDetailView.as_view(), name='payroll_detail'),
    path('payroll/<uuid:pk>/process/', PayrollProcessView.as_view(), name='payroll_process'),
    # Recruitment
    path('recruitment/jobs/', __import__('apps.hrms.views', fromlist=['JobPostingListView']).JobPostingListView.as_view(), name='job_postings'),
    path('recruitment/jobs/<uuid:pk>/', __import__('apps.hrms.views', fromlist=['JobPostingDetailView']).JobPostingDetailView.as_view(), name='job_posting_detail'),
    path('recruitment/applications/', __import__('apps.hrms.views', fromlist=['JobApplicationListView']).JobApplicationListView.as_view(), name='job_applications'),
    path('recruitment/applications/<uuid:pk>/', __import__('apps.hrms.views', fromlist=['JobApplicationDetailView']).JobApplicationDetailView.as_view(), name='application_detail'),
    
    # Appraisals, Training, Expenses
    path('appraisals/', __import__('apps.hrms.views', fromlist=['PerformanceAppraisalListView']).PerformanceAppraisalListView.as_view(), name='appraisals'),
    path('appraisals/<uuid:pk>/', __import__('apps.hrms.views', fromlist=['PerformanceAppraisalDetailView']).PerformanceAppraisalDetailView.as_view(), name='appraisal_detail'),
    path('training/', __import__('apps.hrms.views', fromlist=['TrainingProgramListView']).TrainingProgramListView.as_view(), name='training_programs'),
    path('training/<uuid:pk>/', __import__('apps.hrms.views', fromlist=['TrainingProgramDetailView']).TrainingProgramDetailView.as_view(), name='training_program_detail'),
    path('expenses/', __import__('apps.hrms.views', fromlist=['ExpenseClaimListView']).ExpenseClaimListView.as_view(), name='expense_claims'),
    path('expenses/<uuid:pk>/', __import__('apps.hrms.views', fromlist=['ExpenseClaimDetailView']).ExpenseClaimDetailView.as_view(), name='expense_claim_detail'),
]
