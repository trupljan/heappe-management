
def build_connection_strings_from_container(container_name: str, password: str):
    """Builds connection strings using MSSQL container name instead of IP/port."""
    MiddlewareContext = f"Server={container_name};Database=heappe;User=SA;Password={password};TrustServerCertificate=True;"
    Logging = f"Server={container_name};Database=heappe-monitoring;User=SA;Password={password};TrustServerCertificate=True;"
    return {
        "MiddlewareContext": MiddlewareContext,
        "Logging": Logging
    }

def generate_appsettings_v6_0_0(
        instance_name: str,
            sa_password: str,
            port: int = 5000,
            automigrate: bool = True,
            version: str = None,
            deployed_ip: str = None):
    appsettings = {
            "Logging": {
                "LogLevel": {
                    "Default": "Information",
                    "Microsoft": "Warning",
                    "Microsoft.Hosting.Lifetime": "Information"
                }
            },
            "ConnectionStrings": build_connection_strings_from_container(f"{instance_name}_mssql", sa_password),
            "DatabaseMigrationSettings": {
                "AutoMigrateDatabase": bool(automigrate),
            },
            "ApplicationAPISettings": {
                "AllowedHosts": [
                    f"http://localhost:{port}"
                ],
                "DeploymentSettings": {
                    "Name": f"{instance_name} instance",
                    "Description": f"Deployment for instance {instance_name}",
                    "Version": version,
                    "DeployedIPAddress": deployed_ip,
                    "Port": str(port),
                    "Host": f"http://{deployed_ip}:{port}",
                    "HostPostfix": f"{instance_name}",
                    "DeploymentEnvironmentType": "Docker",
                    "ResourceAllocationInfrastructureTypes": [
                        "HPC"
                    ]
                },
                "SwaggerDocSettings": {
                    "Title": "HEAppE Web API",
                    "DetailedJobReportingTitle": "Detailed Job Reporting API",
                    "Description": f"HEAppE middleware API {version}",
                    "PrefixDocPath": "swagger",
                    "TermOfUsageUrl": "https://heappe.eu",
                    "License": "GNU General Public License v3.0",
                    "LicenseUrl": "https://www.gnu.org/licenses/gpl-3.0.html",
                    "ContactName": "IT4Innovations",
                    "ContactEmail": "support.heappe@it4i.cz",
                    "ContactUrl": "https://twitter.com/it4innovations"
                }
            },
            "BackGroundThreadSettings": {
                "GetAllJobsInformationCheck": 30,
                "CloseConnectionToFinishedJobsCheck": 30,
                "ClusterAccountRotationJobCheck": 30,
                "FileTransferKeyRemovalCheck": 10800
            },
            "BusinessLogicSettings": {
                "SharedAccountsPoolMode": True,
                "AutomaticClusterAccountInitialization": True,
                "GeneratedFileTransferKeyLimitPerJob": 5,
                "ValidityOfTemporaryTransferKeysInHours": 24,
                "SessionExpirationInSeconds": 900,
                "HTTPRequestConnectionTimeoutInSeconds": 10
            },
            "CertificateGeneratorSettings": {
                "GeneratedKeysDirectory": "/opt/heappe/keys/",
                "GeneratedKeyPrefix": "key",
                "CipherSettings": {
                    "TypeName": "ED25519",
                    "Size": 0
                }
            },
            "HPCConnectionFrameworkSettings": {
                "GenericCommandKeyParameter": "#HEAPPE_PARAM",
                "JobArrayDbDelimiter": "<JOB_ARRAY_ITERATION>",
                "TunnelSettings": {
                    "LocalhostName": "127.0.0.1",
                    "MinLocalPort": 4000,
                    "MaxLocalPort": 4100
                },
                "ClustersConnectionPoolSettings": {
                    "ConnectionPoolCleaningInterval": 60,
                    "ConnectionPoolMaxUnusedInterval": 1800
                },
                "SshClientSettings": {
                    "ConnectionRetryAttempts": 10,
                    "ConnectionTimeout": 30000
                },
                "ScriptsSettings": {
                    "ClusterScriptsRepository": "https://github.com/It4innovations/HEAppE-scripts.git",
                    "KeyScriptsDirectoryInRepository": "HEAppE-scripts/HPC/.key_scripts/",
                    "InstanceIdentifierPath": f"{instance_name}",
                    "SubExecutionsPath": "HEAppE/Executions",
                    "JobLogArchiveSubPath": "HEAppE/Jobs",
                    "SubScriptsPath": "HEAppE/Scripts",
                    "ScriptsBasePath": "~/.HEAppE",
                    "CommandScriptsPathSettings": {
                        "AddFiletransferKeyCmdScriptName": "add_key.sh",
                        "RemoveFiletransferKeyCmdScriptName": "remove_key.sh",
                        "CreateJobDirectoryCmdScriptName": "create_job_directory.sh",
                        "ExecuteCmdScriptName": "run_command.sh",
                        "CopyDataFromTempCmdScriptName": "copy_data_from_temp.sh",
                        "CopyDataToTempCmdScriptName": "copy_data_to_temp.sh"
                    },
                    "LinuxLocalCommandScriptPathSettings": {
                        "ScriptsBasePath": "~/.local_hpc_scripts",
                        "PrepareJobDirCmdScriptName": "prepare_job_dir.sh",
                        "RunLocalCmdScriptName": "run_local.sh",
                        "GetJobInfoCmdScriptName": "get_job_info.sh",
                        "CountJobsCmdScriptName": "count_jobs.sh",
                        "CancelJobCmdScriptName": "cancel_job.sh"
                    }
                }
            },
            "IpRateLimiting": {
                "EnableEndpointRateLimiting": True,
                "StackBlockedRequests": False,
                "RealIpHeader": "X-Real-IP",
                "ClientIdHeader": "X-ClientId",
                "HttpStatusCode": 429,
                "EndpointWhitelist": ["get:/swagger/*"],
                "ClientWhitelist": ["127.0.0.1"],
                "DisableRateLimitHeaders": False,
                "GeneralRules": [
                    {"Endpoint": "*", "Period": "1h", "Limit": 1000}
                ]
            },
            "IpRateLimitPolicies": {
                "IpRules": [
                    {
                        "Ip": "127.0.0.1",
                        "Rules": [{"Endpoint": "*", "Period": "1h", "Limit": 1000}]
                    }
                ]
            },
            "ExternalAuthenticationSettings": {
                "BaseUrl": "",
                "Protocol": "openid-connect",
                "RealmName": "",
                "ClientId": "",
                "SecretId": "",
                "ConnectionTimeout": 15,
                "AllowedClientIds": [],
                "RoleMapping": {
                    "prj_list": "Maintainer",
                    "prj_read": "Reporter",
                    "prj_write": "Submitter"
                },
                "Projects": [
                    {
                        "UUID": "",
                        "Name": "",
                        "HEAppEGroupName": "OpenIDGroup"
                    }
                ],
                "HEAppEUserPrefix": "Open-Id_",
                "LexisAuthenticationConfiguration": {
                    "BaseAddress": "",
                    "EndpointPrefix": "userorg",
                    "ExtendedUserInfoEndpoint": "/api/UserInfo/Extended",
                    "HEAppEGroupNamePrefix": "LEXIS ",
                    "HEAppEUserPrefix": "LEXIS_<USERNAME>",
                    "RoleMapping": {
                        "Submitter": "heappe_exec",
                        "Manager": "heappe_manager"
                    }
                }
            },
            "OpenStackSettings": {
                "IdentityPort": 5000,
                "ConnectionTimeout": 15,
                "OpenStackVersion": 3,
                "OpenStackSessionExpiration": 1800
            },
            "ClusterManagementLogMessageRedactingRegex": r"(/[^ ]+)|(\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b)",
            "VaultConnectorSettings": {
                "VaultBaseAddress": "http://vaultagent:8100",
                "ClusterVaultAuthenticationCredentialsPath": "v1/HEAppE/data/ClusterAuthenticationCredentials"
            },
            "HealthCheckSettings": {
                "HealthChecksCacheExpirationMs": 10000
            }
        }
    return appsettings