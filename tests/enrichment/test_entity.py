import pytest
from pipeline.enrichment.entity import (
    Entity, EntityTypeSpec, ENTITY_TYPES,
    InvalidEntityTypeError, make_entity,
)

TS = "2026-06-02T21:00:00Z"


class TestEntityTypeRegistry:
    def test_all_24_types_present(self):
        expected = {
            "handle", "display_name", "bio_url", "email", "gmail", "domain",
            "subdomain", "youtube_channel_id", "youtube_handle", "tiktok_handle",
            "twitter_handle", "instagram_handle", "linkedin_url", "github_handle",
            "reddit_username", "twitch_handle", "spotify_artist_id", "podcast_url",
            "podcast_itunes_id", "substack_url", "website_url", "wikidata_id",
            "cnpj", "phone",
        }
        assert set(ENTITY_TYPES.keys()) == expected

    def test_each_spec_has_required_fields(self):
        for name, spec in ENTITY_TYPES.items():
            assert hasattr(spec, "pattern"), name
            assert hasattr(spec, "normalizer"), name
            assert hasattr(spec, "osint_risk"), name
            assert hasattr(spec, "example"), name

    def test_osint_risk_types(self):
        assert ENTITY_TYPES["email"].osint_risk is True
        assert ENTITY_TYPES["gmail"].osint_risk is True
        assert ENTITY_TYPES["cnpj"].osint_risk is True
        assert ENTITY_TYPES["phone"].osint_risk is True
        assert ENTITY_TYPES["handle"].osint_risk is False
        assert ENTITY_TYPES["youtube_channel_id"].osint_risk is False


class TestNormalizers:
    def test_handle_strips_at(self):
        assert ENTITY_TYPES["handle"].normalizer("@filipelauar") == "filipelauar"

    def test_handle_lowercases(self):
        assert ENTITY_TYPES["handle"].normalizer("FilipeLauar") == "filipelauar"

    def test_email_lowercases(self):
        assert ENTITY_TYPES["email"].normalizer("Foo@Bar.COM") == "foo@bar.com"

    def test_domain_strips_www(self):
        assert ENTITY_TYPES["domain"].normalizer("www.vidacomia.com") == "vidacomia.com"

    def test_cnpj_strips_punctuation(self):
        assert ENTITY_TYPES["cnpj"].normalizer("12.345.678/0001-90") == "12345678000190"

    def test_cnpj_wrong_length_raises(self):
        with pytest.raises(ValueError, match="14 digits"):
            ENTITY_TYPES["cnpj"].normalizer("123")

    def test_phone_e164(self):
        result = ENTITY_TYPES["phone"].normalizer("+55 31 9999-1234")
        assert result == "+55319999 1234".replace(" ", "")

    def test_youtube_handle_adds_at(self):
        assert ENTITY_TYPES["youtube_handle"].normalizer("vidacomia") == "@vidacomia"

    def test_youtube_handle_keeps_existing_at(self):
        assert ENTITY_TYPES["youtube_handle"].normalizer("@vidacomia") == "@vidacomia"

    def test_wikidata_uppercases(self):
        assert ENTITY_TYPES["wikidata_id"].normalizer("q12345") == "Q12345"

    def test_spotify_adds_prefix(self):
        assert ENTITY_TYPES["spotify_artist_id"].normalizer("abc123") == "spotify:artist:abc123"

    def test_spotify_keeps_existing_prefix(self):
        assert ENTITY_TYPES["spotify_artist_id"].normalizer("spotify:artist:abc123") == "spotify:artist:abc123"

    def test_url_lowercases_host(self):
        result = ENTITY_TYPES["bio_url"].normalizer("HTTPS://LinkTr.ee/vidacomia")
        assert result == "https://linktr.ee/vidacomia"

    def test_url_strips_trailing_slash(self):
        assert ENTITY_TYPES["website_url"].normalizer("https://example.com/") == "https://example.com"


class TestEntityDataclass:
    def test_valid_entity_constructs(self):
        e = Entity(
            type="handle", value="filipelauar",
            source="seed", confidence=1.0, depth=0, discovered_at=TS,
        )
        assert e.value == "filipelauar"

    def test_unknown_type_raises(self):
        with pytest.raises(InvalidEntityTypeError):
            Entity(type="bogus_type", value="x", source="seed",
                   confidence=1.0, depth=0, discovered_at=TS)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError, match="depth"):
            Entity(type="handle", value="foo", source="seed",
                   confidence=1.0, depth=-1, discovered_at=TS)

    def test_confidence_clamped_silently(self):
        e = Entity(type="handle", value="foo", source="seed",
                   confidence=1.5, depth=0, discovered_at=TS)
        assert e.confidence == 1.0

    def test_confidence_negative_clamped_to_zero(self):
        e = Entity(type="handle", value="foo", source="seed",
                   confidence=-0.5, depth=0, discovered_at=TS)
        assert e.confidence == 0.0

    def test_bad_timestamp_raises(self):
        with pytest.raises(ValueError, match="ISO 8601"):
            Entity(type="handle", value="foo", source="seed",
                   confidence=1.0, depth=0, discovered_at="not-a-date")

    def test_unnormalized_value_raises(self):
        with pytest.raises(ValueError, match="normalized"):
            Entity(type="handle", value="@foo",
                   source="seed", confidence=1.0, depth=0, discovered_at=TS)

    def test_frozen(self):
        e = Entity(type="handle", value="foo", source="seed",
                   confidence=1.0, depth=0, discovered_at=TS)
        with pytest.raises(Exception):
            e.value = "bar"  # type: ignore


class TestMakeEntity:
    def test_make_entity_normalizes_handle(self):
        e = make_entity("handle", "@FilipeLauar", source="seed", confidence=1.0, depth=0)
        assert e.value == "filipelauar"

    def test_make_entity_cnpj(self):
        e = make_entity("cnpj", "12.345.678/0001-90", source="cnpj", confidence=0.9, depth=1)
        assert e.value == "12345678000190"

    def test_make_entity_sets_discovered_at(self):
        e = make_entity("handle", "foo", source="seed", confidence=1.0, depth=0)
        assert e.discovered_at.endswith("Z")

    def test_make_entity_invalid_type_raises(self):
        with pytest.raises(InvalidEntityTypeError):
            make_entity("not_real", "foo", source="s", confidence=1.0, depth=0)
