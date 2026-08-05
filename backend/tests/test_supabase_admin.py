from unittest.mock import Mock, patch

from app.core import supabase_admin


def _response(users):
    response = Mock()
    response.json.return_value = {"users": users}
    response.raise_for_status.return_value = None
    return response


@patch("app.core.supabase_admin.httpx.get")
def test_get_user_by_email_uses_exact_case_insensitive_match(mock_get):
    mock_get.return_value = _response([
        {"id": "wrong", "email": "someone@example.com"},
        {"id": "right", "email": "Demo@Example.com"},
    ])

    user = supabase_admin.get_user_by_email("demo@example.com")

    assert user == {"id": "right", "email": "Demo@Example.com"}
    assert mock_get.call_args.kwargs["params"] == {"page": 1, "per_page": 1000}


@patch("app.core.supabase_admin.httpx.get")
def test_get_user_by_email_does_not_return_unrelated_first_user(mock_get):
    mock_get.return_value = _response([
        {"id": "wrong", "email": "someone@example.com"},
    ])

    assert supabase_admin.get_user_by_email("missing@example.com") is None


@patch("app.core.supabase_admin.httpx.put")
def test_update_user_password_uses_admin_user_endpoint(mock_put):
    mock_put.return_value = _response([])
    mock_put.return_value.json.return_value = {"id": "user-1"}

    result = supabase_admin.update_user_password("user-1", "Password234@")

    assert result == {"id": "user-1"}
    assert mock_put.call_args.kwargs["json"] == {
        "password": "Password234@",
        "email_confirm": True,
    }


@patch("app.core.supabase_admin.httpx.post")
def test_create_user_can_preserve_existing_local_profile_id(mock_post):
    mock_post.return_value = _response([])
    mock_post.return_value.json.return_value = {"id": "local-profile-id"}

    user = supabase_admin.create_user(
        "demo@example.com",
        "Password234@",
        email_confirm=True,
        user_id="local-profile-id",
    )

    assert user == {"id": "local-profile-id"}
    assert mock_post.call_args.kwargs["json"]["id"] == "local-profile-id"
