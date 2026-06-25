"""
Authentication REST API
JWT login, user management, RBAC endpoints
"""

from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import serializers, viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.authentication.models import (
    User, UserCompany, Role, Permission, ModulePermission,
    ActivityLog, UserSession
)


# ─── Serializers ──────────────────────────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    company_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name', 'phone',
            'role', 'is_active', 'is_email_verified', 'language', 'timezone',
            'theme', 'two_factor_enabled', 'avatar', 'last_active',
            'date_joined', 'company_name',
        ]
        read_only_fields = ['id', 'email', 'date_joined', 'last_active']

    def get_company_name(self, obj):
        return obj.primary_company.name if obj.primary_company else None


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            'email', 'first_name', 'last_name', 'phone', 'password',
            'password_confirm', 'role', 'language', 'timezone',
        ]

    def validate(self, attrs):
        if attrs['password'] != attrs.pop('password_confirm'):
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'language', 'timezone', 'theme', 'avatar']


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({'new_password_confirm': 'Passwords do not match.'})
        return attrs


class CustomTokenObtainSerializer(serializers.Serializer):
    """JWT login with extra user data in response."""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        user = authenticate(username=email, password=password)
        if not user:
            raise serializers.ValidationError('Invalid credentials.')
        if not user.is_active:
            raise serializers.ValidationError('Account is deactivated.')
        if user.is_locked:
            raise serializers.ValidationError('Account is temporarily locked.')

        refresh = RefreshToken.for_user(user)
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
        }


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = ['id', 'user_name', 'action', 'module', 'resource_type',
                  'description', 'ip_address', 'created_at']

    def get_user_name(self, obj):
        return obj.user.full_name if obj.user else 'System'


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ['id', 'name', 'code', 'description', 'is_system', 'created_at']
        read_only_fields = ['id', 'created_at']


class ModulePermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModulePermission
        fields = ['id', 'role', 'module', 'can_create', 'can_read',
                  'can_update', 'can_delete', 'can_approve', 'can_export']


# ─── API Views ────────────────────────────────────────────────────────────────

class LoginAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = CustomTokenObtainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_data = serializer.validated_data
        user = User.objects.get(email=request.data['email'])

        # Update login metadata
        user.failed_login_attempts = 0
        user.last_login_ip = self._get_ip(request)
        user.save(update_fields=['failed_login_attempts', 'last_login_ip'])

        ActivityLog.objects.create(
            user=user, company=user.primary_company,
            action='login', module='auth',
            ip_address=self._get_ip(request),
        )

        return Response({
            'success': True,
            'data': user_data,
        }, status=status.HTTP_200_OK)

    @staticmethod
    def _get_ip(request):
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')


class LogoutAPIView(APIView):
    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass

        ActivityLog.objects.create(
            user=request.user, company=request.user.primary_company,
            action='logout', module='auth',
        )
        return Response({'success': True, 'message': 'Logged out successfully.'})


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        if self.action in ['update', 'partial_update']:
            return UserUpdateSerializer
        return UserSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.SUPER_ADMIN:
            return User.objects.all()
        return User.objects.filter(companies=user.primary_company)

    @action(detail=False, methods=['get', 'patch'])
    def me(self, request):
        if request.method == 'GET':
            serializer = UserSerializer(request.user)
            return Response(serializer.data)
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=['post'])
    def change_password(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not request.user.check_password(serializer.validated_data['old_password']):
            return Response(
                {'error': 'Old password is incorrect.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()

        # Re-generate tokens
        refresh = RefreshToken.for_user(request.user)
        return Response({
            'success': True,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        })

    @action(detail=False, methods=['get'])
    def activity_logs(self, request):
        logs = ActivityLog.objects.filter(user=request.user).order_by('-created_at')[:50]
        serializer = ActivityLogSerializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        user = self.get_object()
        if user == request.user:
            return Response({'error': 'Cannot deactivate your own account.'}, status=400)
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        return Response({'success': True, 'is_active': user.is_active})

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        """Admin-initiated password reset link."""
        from apps.authentication.services import AuthService
        user = self.get_object()
        service = AuthService()
        service.send_password_reset_email(user, request)
        return Response({'success': True, 'message': 'Password reset email sent.'})


class RoleViewSet(viewsets.ModelViewSet):
    serializer_class = RoleSerializer

    def get_queryset(self):
        return Role.objects.filter(company=self.request.user.primary_company)

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.primary_company)


class ModulePermissionViewSet(viewsets.ModelViewSet):
    serializer_class = ModulePermissionSerializer
    queryset = ModulePermission.objects.all()

    def get_queryset(self):
        qs = super().get_queryset()
        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(role=role)
        return qs


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ActivityLogSerializer

    def get_queryset(self):
        user = self.request.user
        qs = ActivityLog.objects.filter(company=user.primary_company).order_by('-created_at')
        # Filter by current user unless admin
        if user.role not in (User.Role.SUPER_ADMIN, User.Role.COMPANY_ADMIN):
            qs = qs.filter(user=user)
        return qs
