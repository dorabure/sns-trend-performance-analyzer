"""DTO-to-business normalization; raw API parsing remains in each provider."""
from app.dto.normalized import NormalizedPost, NormalizedAccountMetric, Platform, SourceType, MediaType
from app.providers.core import NormalizedAccountProfile, ProviderError


class DTOProviderNormalizer:
    def __init__(self, provider_type, media_mapping=None):
        self.platform = Platform({'X_API': 'X', 'INSTAGRAM_API': 'INSTAGRAM'}[provider_type])
        self.media_mapping = media_mapping or {}

    def normalize_account(self, account, observed_at):
        profile = NormalizedAccountProfile(self.platform, account.remote_account_id, account.username,
            account.display_name, account.profile_url)
        values = account.metrics.values
        metric = NormalizedAccountMetric(self.platform, account.username, observed_at.date(),
            **{name: values.get(name) for name in ('followers', 'following', 'post_count')}, raw_metrics=dict(values))
        return profile, metric

    def normalize_posts(self, posts, account):
        try:
            return [NormalizedPost(SourceType.OWN, self.platform, post.remote_post_id, post.posted_at,
                account_name=account.username, text=post.text,
                media_type=MediaType(self.media_mapping.get(post.media_kind, post.media_kind)),
                permalink=post.permalink, hashtags=post.hashtags, raw_data=post.safe_raw,
                **{name: post.metrics.values.get(name) for name in ('impressions', 'reach', 'views', 'likes', 'comments', 'shares', 'saves')}) for post in posts]
        except Exception:
            raise ProviderError('PROVIDER_RESPONSE_INVALID') from None
