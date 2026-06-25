from rest_framework import serializers

from .models import (
    Credential,
    Host,
    Installation,
    InstallationTarget,
    InstallationTemplate,
)


class CredentialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Credential
        fields = "__all__"

    def validate(self, attrs):
        auth_type = attrs.get("auth_type", getattr(self.instance, "auth_type", None))
        private_key = attrs.get("private_key", getattr(self.instance, "private_key", ""))
        password = attrs.get("password", getattr(self.instance, "password", ""))

        if auth_type == Credential.AuthType.SSH_KEY and not private_key:
            raise serializers.ValidationError(
                {"private_key": "This field is required when auth_type is 'ssh_key'."}
            )

        if auth_type == Credential.AuthType.PASSWORD and not password:
            raise serializers.ValidationError(
                {"password": "This field is required when auth_type is 'password'."}
            )

        return attrs


class HostSerializer(serializers.ModelSerializer):
    credential_name = serializers.CharField(source="credential.name", read_only=True)

    class Meta:
        model = Host
        fields = "__all__"


class InstallationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstallationTemplate
        fields = "__all__"


class InstallationTargetSerializer(serializers.ModelSerializer):
    host_name = serializers.CharField(source="host.name", read_only=True)

    class Meta:
        model = InstallationTarget
        fields = "__all__"


class InstallationSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source="template.name", read_only=True)
    targets = InstallationTargetSerializer(many=True, read_only=True)

    class Meta:
        model = Installation
        fields = "__all__"
