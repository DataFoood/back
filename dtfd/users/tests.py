from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from users.models import User


def make_user(email="user@dtfd.com", password="SenhaForte123", name="User Teste", **extra):
    return User.objects.create_user(email=email, password=password, name=name, **extra)


def make_admin(email="admin@dtfd.com", password="SenhaForte123", name="Admin"):
    return User.objects.create_superuser(email=email, password=password, name=name)


# ---------------------------------------------------------------------------
# REGISTER
# ---------------------------------------------------------------------------
class UserRegisterTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.URL = "/api/users/register/"
        cls.maxDiff = None
        cls.valid = {
            "name": "Lucira Buster",
            "email": "lucira@dtfd.com",
            "cpf": "12345678901",
            "phone": "11999998888",
            "password": "SenhaForte123",
            "confirm_password": "SenhaForte123",
        }

    def setUp(self):
        cache.clear()  # zera contador de throttle entre testes

    # --- happy ---
    def test_register_success(self):
        response = self.client.post(self.URL, data=self.valid, format="json")

        with self.subTest():
            self.assertEqual(status.HTTP_201_CREATED, response.status_code)

        returned = response.json()
        expected_fields = {"id", "name", "email", "cpf", "phone"}
        self.assertSetEqual(expected_fields, set(returned.keys()),
                            "Register deve retornar id/name/email/cpf/phone e nunca a senha")
        self.assertNotIn("password", returned)

    def test_register_persists_and_hashes_password(self):
        self.client.post(self.URL, data=self.valid, format="json")
        user = User.objects.get(email="lucira@dtfd.com")
        self.assertNotEqual(user.password, "SenhaForte123", "Senha deve ser hasheada")
        self.assertTrue(user.check_password("SenhaForte123"))

    # --- unhappy ---
    def test_register_without_required_fields(self):
        response = self.client.post(self.URL, data={}, format="json")

        with self.subTest():
            self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

        expected_fields = {"name", "email", "password", "confirm_password"}
        self.assertSetEqual(expected_fields, set(response.json().keys()),
                            "Faltando campos obrigatorios deve apontar todos")

    def test_register_password_mismatch(self):
        data = {**self.valid, "confirm_password": "Outra123"}
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("confirm_password", response.json())

    def test_register_invalid_email(self):
        data = {**self.valid, "email": "nao-eh-email"}
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("email", response.json())

    def test_register_weak_password(self):
        data = {**self.valid, "password": "123", "confirm_password": "123"}
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("password", response.json())

    def test_register_duplicate_email(self):
        make_user(email="lucira@dtfd.com")
        response = self.client.post(self.URL, data=self.valid, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("email", response.json())

    def test_register_sql_injection_is_treated_as_data(self):
        payload = {**self.valid, "name": "Robert'); DROP TABLE users_user;--"}
        response = self.client.post(self.URL, data=payload, format="json")
        # ORM parametriza: vira dado literal, tabela intacta
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        self.assertEqual(1, User.objects.filter(email="lucira@dtfd.com").count())


# ---------------------------------------------------------------------------
# LOGIN (JWT)
# ---------------------------------------------------------------------------
class UserLoginTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.URL = "/api/users/login/"
        cls.maxDiff = None
        cls.password = "SenhaForte123"
        cls.user = make_user(email="lucira@dtfd.com", password=cls.password)

    def setUp(self):
        cache.clear()  # zera contador de throttle entre testes

    # --- happy ---
    def test_login_success(self):
        data = {"email": "lucira@dtfd.com", "password": self.password}
        response = self.client.post(self.URL, data=data, format="json")

        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)

        self.assertSetEqual({"access", "refresh"}, set(response.json().keys()),
                            "Login deve retornar access e refresh")

    # --- unhappy ---
    def test_login_without_required_fields(self):
        response = self.client.post(self.URL, data={}, format="json")

        with self.subTest():
            self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

        self.assertSetEqual({"email", "password"}, set(response.json().keys()))

    def test_login_wrong_credentials(self):
        data = {"email": "lucira@dtfd.com", "password": "errada"}
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_login_soft_deleted_user_blocked(self):
        self.user.deleted_at = timezone.now()
        self.user.is_active = False
        self.user.save(update_fields=["deleted_at", "is_active"])
        data = {"email": "lucira@dtfd.com", "password": self.password}
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)


# ---------------------------------------------------------------------------
# DETAIL
# ---------------------------------------------------------------------------
class UserDetailTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user(email="owner@dtfd.com")
        cls.other = make_user(email="other@dtfd.com")
        cls.URL = f"/api/users/{cls.owner.pk}/"

    # --- happy ---
    def test_detail_own(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.URL)
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        expected = {"id", "name", "email", "cpf", "phone", "birthday", "gender",
                    "avatar_url", "banner_url", "role", "level", "allow_info",
                    "is_active", "created_at"}
        self.assertSetEqual(expected, set(response.json().keys()))

    def test_detail_another_user_readable(self):
        # leitura de outro usuario e permitida (SAFE method)
        self.client.force_authenticate(self.other)
        response = self.client.get(self.URL)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    # --- unhappy ---
    def test_detail_unauthenticated(self):
        response = self.client.get(self.URL)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_detail_not_found(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get("/api/users/99999/")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)


# ---------------------------------------------------------------------------
# EDIT
# ---------------------------------------------------------------------------
class UserEditTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user(email="owner@dtfd.com")
        cls.other = make_user(email="other@dtfd.com")
        cls.admin = make_admin()
        cls.URL = f"/api/users/{cls.owner.pk}/"

    # --- happy ---
    def test_edit_own(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(self.URL, data={"name": "Novo Nome"}, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.owner.refresh_from_db()
        self.assertEqual("Novo Nome", self.owner.name)

    def test_edit_by_admin(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(self.URL, data={"name": "Admin Editou"}, format="json")
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    # --- unhappy ---
    def test_edit_another_user_forbidden(self):
        self.client.force_authenticate(self.other)
        response = self.client.patch(self.URL, data={"name": "Hacker"}, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_edit_unauthenticated(self):
        response = self.client.patch(self.URL, data={"name": "X"}, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

    def test_edit_role_is_readonly(self):
        # role nao pode ser escalado via edit
        self.client.force_authenticate(self.owner)
        self.client.patch(self.URL, data={"role": "admin"}, format="json")
        self.owner.refresh_from_db()
        self.assertNotEqual("admin", self.owner.role)


# ---------------------------------------------------------------------------
# REMOVE (soft delete)
# ---------------------------------------------------------------------------
class UserRemoveTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user(email="owner@dtfd.com")
        cls.other = make_user(email="other@dtfd.com")
        cls.URL = f"/api/users/{cls.owner.pk}/delete/"

    # --- happy ---
    def test_soft_delete_own(self):
        self.client.force_authenticate(self.owner)
        response = self.client.delete(self.URL)
        with self.subTest():
            self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        # sumiu do manager padrao, mas existe em all_objects com deleted_at
        self.assertFalse(User.objects.filter(pk=self.owner.pk).exists())
        deleted = User.all_objects.get(pk=self.owner.pk)
        self.assertIsNotNone(deleted.deleted_at)
        self.assertFalse(deleted.is_active)

    # --- unhappy ---
    def test_remove_another_user_forbidden(self):
        self.client.force_authenticate(self.other)
        response = self.client.delete(self.URL)
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_remove_unauthenticated(self):
        response = self.client.delete(self.URL)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)


# ---------------------------------------------------------------------------
# LIST REMOVED (admin)
# ---------------------------------------------------------------------------
class UserRemovedListTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_admin()
        cls.common = make_user(email="common@dtfd.com")
        cls.removed = make_user(email="removed@dtfd.com")
        cls.URL = "/api/users/removed/"

    def setUp(self):
        # soft delete um usuario
        self.removed.deleted_at = timezone.now()
        self.removed.is_active = False
        self.removed.save(update_fields=["deleted_at", "is_active"])

    # --- happy ---
    def test_list_removed_as_admin(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.URL)
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        ids = {u["id"] for u in response.json()["results"]}
        self.assertIn(self.removed.pk, ids)
        self.assertNotIn(self.common.pk, ids, "Usuario ativo nao deve aparecer em removidos")

    # --- unhappy ---
    def test_list_removed_as_common_forbidden(self):
        self.client.force_authenticate(self.common)
        response = self.client.get(self.URL)
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_list_removed_unauthenticated(self):
        response = self.client.get(self.URL)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)


# ---------------------------------------------------------------------------
# SECURITY — escalacao de privilegio / mass assignment
# ---------------------------------------------------------------------------
class UserPrivilegeEscalationTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.REGISTER = "/api/users/register/"

    def test_register_cannot_set_staff_or_superuser(self):
        payload = {
            "name": "Atacante",
            "email": "atk@dtfd.com",
            "password": "SenhaForte123",
            "confirm_password": "SenhaForte123",
            "is_staff": True,
            "is_superuser": True,
            "role": "admin",
            "level": 99,
        }
        response = self.client.post(self.REGISTER, data=payload, format="json")
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        user = User.objects.get(email="atk@dtfd.com")
        self.assertFalse(user.is_staff, "is_staff nao pode ser setado no register")
        self.assertFalse(user.is_superuser, "is_superuser nao pode ser setado no register")
        self.assertEqual("customer", user.role, "role nao pode ser setado no register")
        self.assertEqual(1, user.level, "level nao pode ser setado no register")

    def test_edit_cannot_escalate_privileges(self):
        victim = make_user(email="v@dtfd.com")
        self.client.force_authenticate(victim)
        payload = {
            "is_staff": True,
            "is_superuser": True,
            "is_active": False,
            "role": "admin",
            "level": 99,
        }
        self.client.patch(f"/api/users/{victim.pk}/", data=payload, format="json")
        victim.refresh_from_db()
        self.assertFalse(victim.is_staff)
        self.assertFalse(victim.is_superuser)
        self.assertTrue(victim.is_active)
        self.assertEqual("customer", victim.role)
        self.assertEqual(1, victim.level)


# ---------------------------------------------------------------------------
# CHANGE PASSWORD
# ---------------------------------------------------------------------------
class UserChangePasswordTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "SenhaForte123"
        cls.user = make_user(email="cp@dtfd.com", password=cls.password)
        cls.other = make_user(email="cpother@dtfd.com")
        cls.URL = f"/api/users/{cls.user.pk}/change-password/"

    # --- happy ---
    def test_change_password_success(self):
        self.client.force_authenticate(self.user)
        data = {
            "current_password": self.password,
            "new_password": "NovaSenha456",
            "confirm_password": "NovaSenha456",
        }
        response = self.client.post(self.URL, data=data, format="json")
        with self.subTest():
            self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NovaSenha456"))

    # --- unhappy ---
    def test_change_password_wrong_current(self):
        self.client.force_authenticate(self.user)
        data = {
            "current_password": "errada",
            "new_password": "NovaSenha456",
            "confirm_password": "NovaSenha456",
        }
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("current_password", response.json())

    def test_change_password_mismatch(self):
        self.client.force_authenticate(self.user)
        data = {
            "current_password": self.password,
            "new_password": "NovaSenha456",
            "confirm_password": "Diferente789",
        }
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_change_password_of_another_user_forbidden(self):
        self.client.force_authenticate(self.other)
        data = {
            "current_password": "SenhaForte123",
            "new_password": "NovaSenha456",
            "confirm_password": "NovaSenha456",
        }
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_change_password_unauthenticated(self):
        data = {"current_password": "x", "new_password": "y", "confirm_password": "y"}
        response = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)


# ---------------------------------------------------------------------------
# CONSENT (LGPD — allow_info)
# ---------------------------------------------------------------------------
class UserConsentTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user(email="consent@dtfd.com")
        cls.URL = "/api/users/consent/"

    def test_grant_consent(self):
        self.client.force_authenticate(self.user)
        response = self.client.patch(self.URL, data={"allow_info": True}, format="json")
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.user.refresh_from_db()
        self.assertTrue(self.user.allow_info)

    def test_revoke_consent(self):
        self.user.allow_info = True
        self.user.save(update_fields=["allow_info"])
        self.client.force_authenticate(self.user)
        response = self.client.patch(self.URL, data={"allow_info": False}, format="json")
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.user.refresh_from_db()
        self.assertFalse(self.user.allow_info)

    def test_missing_field_rejected(self):
        self.client.force_authenticate(self.user)
        response = self.client.patch(self.URL, data={}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_non_boolean_rejected(self):
        self.client.force_authenticate(self.user)
        response = self.client.patch(self.URL, data={"allow_info": "yes"}, format="json")
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_unauthenticated(self):
        response = self.client.patch(self.URL, data={"allow_info": True}, format="json")
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)


# ---------------------------------------------------------------------------
# THROTTLING (anti brute-force)
# ---------------------------------------------------------------------------
class LoginThrottleTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.URL = "/api/users/login/"
        make_user(email="brute@dtfd.com", password="SenhaForte123")

    def setUp(self):
        cache.clear()

    def test_login_blocks_after_rate_limit(self):
        data = {"email": "brute@dtfd.com", "password": "errada"}
        # rate = 5/min: as 5 primeiras passam (401), a 6a e bloqueada (429)
        for _ in range(5):
            response = self.client.post(self.URL, data=data, format="json")
            self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)
        blocked = self.client.post(self.URL, data=data, format="json")
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, blocked.status_code)
