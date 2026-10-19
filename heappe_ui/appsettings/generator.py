
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
                "AutoInitializeProjectCredentialsOnFirstUse": True,
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
                    "ConnectionPoolMaxUnusedInterval": 60,
                    "MaxConnectionsPerUser": 10,
                    "MaxSessionsPerConnection": 8
                },
                "SshClientSettings": {
                    "ConnectionRetryAttempts": 3,
                    "ConnectionTimeout": 10000
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

def generate_appsettings_v6_1_0(
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
                "AutoInitializeProjectCredentialsOnFirstUse": True,
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
                    "ConnectionPoolMaxUnusedInterval": 60,
                    "MaxConnectionsPerUser": 10,
                    "MaxSessionsPerConnection": 8
                },
                "SshClientSettings": {
                    "ConnectionRetryAttempts": 3,
                    "ConnectionTimeout": 10000
                },
                "ScriptsSettings": {
                    "ClusterScriptsRepository": "https://github.com/It4innovations/HEAppE-scripts.git",
                    "ClusterScriptsRepositoryBranch": "master",
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
                    {"Endpoint": "*", "Period": "1h", "Limit": 100000}
                ]
            },
            "IpRateLimitPolicies": {
                "IpRules": [
                    {
                        "Ip": "127.0.0.1",
                        "Rules": [{"Endpoint": "*", "Period": "1h", "Limit": 100000}]
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
                    "UseBearerAuth": False,
                    "BaseAddress": "",
                    "EndpointPrefix": "userorg",
                    "ExtendedUserInfoEndpoint": "/api/UserInfo/Extended",
                    "HEAppEGroupNamePrefix": "LEXIS ",
                    "HEAppEUserPrefix": "LEXIS_<USERNAME>",
                    "CommandTemplatePermissions": "/api/Heappe/CommandTemplatePermissions/",
                    "CheckCommandTemplatePermissions": False,
                    "RoleMapping": {
                        "Submitter": "perm:heappe:exec",
                        "Manager": "perm:heappe:manager"
                    }
                }
            },
        "JwtTokenIntrospectionConfiguration": {
            "IsEnabled": False,
            "UseCertificateAuthorityForAuthentication": True,
            "Authority": "",
            "ClientId": "",
            "ClientSecret": "",
            "RequireHttps": True,
            "ValidateIssuerName": False,
            "ValidateEndpoints": True,
            "TokenExchangeConfiguration": {
                "ClientId": "",
                "ClientSecret": "",
                "GrantType": "urn:ietf:params:oauth:grant-type:token-exchange",
                "SubjectTokenType": "urn:ietf:params:oauth:token-type:access_token",
                "Audience": ""
            },
            "LexisTokenFlowConfiguration": {
                "IsEnabled": False,
                "BaseUrl": "",
                "Realm": "",
                "Broker": "",
                "Scope": "openid profile email",
                "PollIntervalSeconds": 5,
                "ClientId": "heappe",
                "ClientSecret": ""
            }
        },
            "OpenStackSettings": {
                "IdentityPort": 5000,
                "ConnectionTimeout": 15,
                "OpenStackVersion": 3,
                "OpenStackSessionExpiration": 1800
            },
            "SshCaSettings": {
                "UseCertificateAuthorityForAuthentication": False,
                "UsePosixAccountFromCertificate": True,
                "BaseUri": "https://api.ca.heappe.eu",
                "CAName": "",
                "ConnectionTimeoutInSeconds": 15
            },
            "ClusterManagementLogMessageRedactingRegex": r"(/[^ ]+)|(\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b)",
            "VaultConnectorSettings": {
                "VaultBaseAddress": "http://vaultagent:8100",
                "ClusterVaultAuthenticationCredentialsPath": "v1/HEAppE/data/ClusterAuthenticationCredentials"
            },
             "HealthCheckSettings": {
                    "HealthChecksCacheExpirationMs": 10000
            },
            "DatabaseFullBackupSettings": {
                "ScheduledBackupEnabled": True,
                "ScheduledRuntime": "02:00:00",
                "LocalPath": "/opt/heappe/backups/database",
                "NASPath": "",
                "BackupFileNamePrefix": "HEAppE",
                "RetentionPolicy": {
                    "Daily": 7,
                    "Weekly": 14,
                    "Monthly": 12
                }
            },
            "DatabaseTransactionLogBackupSettings": {
                "ScheduledBackupEnabled": True,
                "BackupScheduleIntervalInMinutes": 60,
                "LocalPath": "/opt/heappe/backups/database/logs",
                "NASPath": "",
                "BackupFileNamePrefix": "HEAppE",
                "RetentionPolicy": {
                    "Daily": 7,
                    "Weekly": 14,
                    "Monthly": 12
                }
            }
        }
    return appsettings

def generate_appsettings_v6_2_0(
        instance_name: str,
            sa_password: str,
            port: int = 5000,
            automigrate: bool = True,
            version: str = None,
            deployed_ip: str = None):
    appsettings = generate_appsettings_v6_1_0(instance_name, sa_password, port, automigrate, version, deployed_ip)
    lexis_auth = appsettings.get('ExternalAuthenticationSettings').get('LexisAuthenticationConfiguration')
    lexis_auth['CommandTemplatePermissions'] = "/api/Heappe/CommandTemplatePermissions/"
    lexis_auth['CheckCommandTemplatePermissions'] = True
    lexis_token_flow = appsettings.get('JwtTokenIntrospectionConfiguration').get('LexisTokenFlowConfiguration')
    lexis_token_flow['UseExpirioServiceForTokenExchange'] = True
    appsettings['ExpirioSettings'] = {
        "BaseUrl": "https://expirio.heappe.eu/api",
        "TimeoutSeconds": 30,
        "MaxRetries": 3,
        "RetryInitialDelayMs": 200,
        "ProviderName": "",
        "TokenName": ""
    }

    return appsettings

def generate_appsettings_v6_2_1(
        instance_name: str,
        sa_password: str,
        port: int = 5000,
        automigrate: bool = True,
        version: str = None,
        deployed_ip: str = None):
    appsettings = generate_appsettings_v6_2_0(instance_name, sa_password, port, automigrate, version, deployed_ip)
    #bgworker RoleAssignmentSyncCheck = 3600
    appsettings['BackGroundThreadSettings']['RoleAssignmentSyncCheck'] = 3600
    appsettings['RoleAssignments'] = {
        "Administrators": ["admin", "sys_admin"],
        "Maintainers": ["sys_maintainer"],
        "Submitters": ["sys_submitter"],
        "GroupReporters": ["sys_reporter"],
        "Reporters": ["sys_reporter"],
        "ManagementAdmins": ["sys_mgmtadmin"],
        "Managers": ["sys_manager"]
    }
    return appsettings

def generate_appsettings_data_staging_v6_0_0(instance_name: str,
            sa_password: str,
            data_staging_token: str,
            port: int = 5001,
            version: str = None):
    appsettings = {
      "Logging": {
        "LogLevel": {
          "Default": "Information",
          "Microsoft": "Warning",
          "Microsoft.AspNetCore": "Warning",
          "Microsoft.Hosting.Lifetime": "Information"
        }
      },
        "ConnectionStrings": build_connection_strings_from_container(f"{instance_name}_mssql", sa_password),
        "IpRateLimiting": {
        "EnableEndpointRateLimiting": True,
        "StackBlockedRequests": False,
        "RealIpHeader": "X-Real-IP",
        "ClientIdHeader": "X-ClientId",
        "HttpStatusCode": 429,
        "EndpointWhitelist": [
          "get:/swagger/*"
        ],
        "ClientWhitelist": [
          "127.0.0.1"
        ],
        "DisableRateLimitHeaders": False,
        "GeneralRules": [
          {
            "Endpoint": "*:/api/DataStaging/*",
            "Period": "1h",
            "Limit": 2000
          }
        ]
      },
      "IpRateLimitPolicies": {
        "IpRules": [
          {
            "Ip": "127.0.0.1",
            "Rules": [
              {
                "Endpoint": "*:/api/DataStaging/*",
                "Period": "1h",
                "Limit": 5000
              }
            ]
          }
        ]
      },
      "ApplicationAPIConfiguration": {
        "AllowedHosts": [
          f"http://localhost:{port}",
        ],
        "AuthenticationParamHeaderName": "AuthKey",
        "AuthenticationToken": data_staging_token,
        "DeploymentConfiguration": {
          "Name": f"{instance_name} data staging",
          "Description": f"Data Staging API for instance {instance_name}",
          "Version": version,
          "DeployedIPAddress": "127.0.0.1"
        },
        "SwaggerConfiguration": {
          "Version": "v1.0.0",
          "Title": "Data-Staging API",
          "Description": "Data-Staging API",
          "Host": f"http://localhost:{port}",
          "HostPostfix": "",
          "PrefixDocPath": "swagger",
          "TermOfUsageUrl": "https://twitter.com/it4innovations",
          "License": "GNU General Public License v3.0",
          "LicenseUrl": "https://www.gnu.org/licenses/gpl-3.0.html",
          "ContactName": "IT4Innovations",
          "ContactEmail": "support.heappe@it4i.cz",
          "ContactUrl": "https://twitter.com/it4innovations"
        }
      }
    }
    return appsettings

def generate_appsettings_data_staging_v6_1_0(instance_name: str,
            sa_password: str,
            data_staging_token: str,
            port: int = 5001,
            version: str = None):
    return generate_appsettings_data_staging_v6_0_0(instance_name,sa_password,data_staging_token,port,version)

def generate_appsettings_data_staging_v6_2_0(instance_name: str,
            sa_password: str,
            data_staging_token: str,
            port: int = 5001,
            version: str = None):
    return generate_appsettings_data_staging_v6_0_0(instance_name,sa_password,data_staging_token,port,version)

def generate_appsettings_data_staging_v6_2_1(instance_name: str,
            sa_password: str,
            data_staging_token: str,
            port: int = 5001,
            version: str = None):

    return generate_appsettings_data_staging_v6_2_0(instance_name,sa_password,data_staging_token,port,version)

def generate_appsettings_v6_4_0(
        instance_name: str,
        sa_password: str,
        port: int = 5000,
        automigrate: bool = True,
        version: str = None,
        deployed_ip: str = None):
    appsettings = generate_appsettings_v6_2_1(instance_name, sa_password, port, automigrate, version, deployed_ip)
    
    if 'HPCConnectionFrameworkSettings' not in appsettings:
        appsettings['HPCConnectionFrameworkSettings'] = {}
    if 'ScriptsSettings' not in appsettings['HPCConnectionFrameworkSettings']:
        appsettings['HPCConnectionFrameworkSettings']['ScriptsSettings'] = {}
        
    appsettings['HPCConnectionFrameworkSettings']['ScriptsSettings']['EventualConsistencyRetryCount'] = 3
    appsettings['HPCConnectionFrameworkSettings']['ScriptsSettings']['EventualConsistencyRetryDelayMs'] = 1000
    return appsettings

def generate_appsettings_data_staging_v6_4_0(instance_name: str,
            sa_password: str,
            data_staging_token: str,
            port: int = 5001,
            version: str = None):
    return generate_appsettings_data_staging_v6_2_1(instance_name, sa_password, data_staging_token, port, version)

def generate_appsettings_v6_4_17(
        instance_name: str,
        sa_password: str,
        port: int = 5000,
        automigrate: bool = True,
        version: str = None,
        deployed_ip: str = None):
    appsettings = generate_appsettings_v6_4_0(instance_name, sa_password, port, automigrate, version, deployed_ip)

    # 1.A. Version and Metadata (ApplicationAPISettings)
    ver_str = version or "v6.4.17"
    if 'ApplicationAPISettings' not in appsettings:
        appsettings['ApplicationAPISettings'] = {}
    if 'DeploymentSettings' not in appsettings['ApplicationAPISettings']:
        appsettings['ApplicationAPISettings']['DeploymentSettings'] = {}
    appsettings['ApplicationAPISettings']['DeploymentSettings']['Version'] = ver_str

    if 'SwaggerDocSettings' not in appsettings['ApplicationAPISettings']:
        appsettings['ApplicationAPISettings']['SwaggerDocSettings'] = {}
    appsettings['ApplicationAPISettings']['SwaggerDocSettings']['DictionaryTitle'] = "Dictionary API"
    appsettings['ApplicationAPISettings']['SwaggerDocSettings']['Description'] = f"HEAppE middleware API {ver_str}"

    # 1.B. BackGroundThreadSettings
    if 'BackGroundThreadSettings' not in appsettings:
        appsettings['BackGroundThreadSettings'] = {}
    appsettings['BackGroundThreadSettings']['ClusterProjectCredentialsCheckConfiguration'] = {
        "IsEnabled": False,
        "IntervalMinutes": 60
    }
    appsettings['BackGroundThreadSettings']['ExternalServiceHealthMonitoringSettings'] = {
        "IsEnabled": True,
        "IntervalSeconds": 60,
        "RetentionDays": 30
    }

    # 1.C. Endpoint Rate Limiting (IpRateLimiting.GeneralRules & IpRateLimitPolicies)
    mgmt_rules = [
        {
            "Endpoint": "*:/heappe/Management/*",
            "Period": "1m",
            "Limit": 120
        },
        {
            "Endpoint": "*:/heappe/UserAndLimitationManagement/*",
            "Period": "1m",
            "Limit": 300
        }
    ]
    if 'IpRateLimiting' not in appsettings:
        appsettings['IpRateLimiting'] = {}
    general_rules = list(appsettings['IpRateLimiting'].get('GeneralRules', []))
    existing_endpoints = {r.get('Endpoint') for r in general_rules if isinstance(r, dict)}
    rules_to_prepend = [r for r in mgmt_rules if r['Endpoint'] not in existing_endpoints]

    catch_all_idx = None
    for idx, r in enumerate(general_rules):
        if isinstance(r, dict) and r.get('Endpoint') == '*':
            catch_all_idx = idx
            r['Limit'] = 1000000
            break
    if catch_all_idx is not None:
        general_rules[catch_all_idx:catch_all_idx] = rules_to_prepend
    else:
        general_rules = rules_to_prepend + general_rules
    appsettings['IpRateLimiting']['GeneralRules'] = general_rules

    if 'IpRateLimitPolicies' in appsettings and 'IpRules' in appsettings['IpRateLimitPolicies']:
        for ip_rule in appsettings['IpRateLimitPolicies']['IpRules']:
            for rule in ip_rule.get('Rules', []):
                if rule.get('Endpoint') == '*':
                    rule['Limit'] = 1000000

    # 1.D. HPCConnectionFrameworkSettings
    if 'HPCConnectionFrameworkSettings' not in appsettings:
        appsettings['HPCConnectionFrameworkSettings'] = {}
    
    if 'ClustersConnectionPoolSettings' not in appsettings['HPCConnectionFrameworkSettings']:
        appsettings['HPCConnectionFrameworkSettings']['ClustersConnectionPoolSettings'] = {}
    appsettings['HPCConnectionFrameworkSettings']['ClustersConnectionPoolSettings']['ConnectionPoolMaxUnusedInterval'] = 1800

    if 'SshClientSettings' not in appsettings['HPCConnectionFrameworkSettings']:
        appsettings['HPCConnectionFrameworkSettings']['SshClientSettings'] = {}
    appsettings['HPCConnectionFrameworkSettings']['SshClientSettings']['ConnectionTimeout'] = 30000

    if 'ScriptsSettings' not in appsettings['HPCConnectionFrameworkSettings']:
        appsettings['HPCConnectionFrameworkSettings']['ScriptsSettings'] = {}
    scripts = appsettings['HPCConnectionFrameworkSettings']['ScriptsSettings']
    scripts['EnableCallback'] = False
    callback_host = f"{deployed_ip}:{port}" if deployed_ip else f"localhost:{port}"
    scripts['CallbackUrl'] = f"https://{callback_host}/heappe/JobManagement/TaskCallback"
    scripts['EnableGracefulTimeout'] = False
    scripts['GracefulTimeoutSeconds'] = 30
    scripts['SshCommandPrefix'] = ""
    scripts['SyncScriptsViaSftp'] = False

    # 1.E. High-Load DB Optimization (BusinessLogicSettings)
    if 'BusinessLogicSettings' not in appsettings:
        appsettings['BusinessLogicSettings'] = {}
    appsettings['BusinessLogicSettings']['SessionLastAccessTimeUpdateIntervalInSeconds'] = 60

    # 1.F. Migration & Backup Encryption (MigrationSettings)
    appsettings['MigrationSettings'] = {
        "EncryptionKey": ""
    }

    # 1.G. ExternalAuthenticationSettings & sub-configurations
    if 'ExternalAuthenticationSettings' in appsettings:
        ext_auth = appsettings['ExternalAuthenticationSettings']
        if 'LexisAuthenticationConfiguration' in ext_auth:
            lexis_auth = ext_auth['LexisAuthenticationConfiguration']
            lexis_auth['ApiVersion'] = "auto"
            lexis_auth['ExtendedUserInfoV2Endpoint'] = "/api/v2/UserInfo/Extended"
            lexis_auth['CommandTemplatePermissionsV2Endpoint'] = "/api/Heappe/CommandTemplatePermissions/"
            lexis_auth['HEAppEUserPrefix'] = "LEXIS_"
            lexis_auth['ConnectionTimeoutInSeconds'] = 10

    if 'JwtTokenIntrospectionConfiguration' in appsettings:
        jwt_cfg = appsettings['JwtTokenIntrospectionConfiguration']
        if 'LexisTokenFlowConfiguration' in jwt_cfg:
            jwt_cfg['LexisTokenFlowConfiguration']['ConnectionTimeoutInSeconds'] = 15

    if 'SshCaSettings' in appsettings:
        appsettings['SshCaSettings']['BaseUri'] = "https://ssh.ca.api.heappe.eu"

    if 'VaultConnectorSettings' in appsettings:
        appsettings['VaultConnectorSettings']['ConnectionTimeoutInSeconds'] = 15

    return appsettings

def generate_appsettings_data_staging_v6_4_17(
        instance_name: str,
        sa_password: str,
        data_staging_token: str,
        port: int = 5001,
        version: str = None):
    return generate_appsettings_data_staging_v6_4_0(instance_name, sa_password, data_staging_token, port, version)

def generate_appsettings_v6_5_0(
        instance_name: str,
        sa_password: str,
        port: int = 5000,
        automigrate: bool = True,
        version: str = None,
        deployed_ip: str = None):
    return generate_appsettings_v6_4_17(
        instance_name, sa_password, port, automigrate, version or "v6.5.0", deployed_ip
    )

def generate_appsettings_data_staging_v6_5_0(
        instance_name: str,
        sa_password: str,
        data_staging_token: str,
        port: int = 5001,
        version: str = None):
    return generate_appsettings_data_staging_v6_4_17(instance_name, sa_password, data_staging_token, port, version)


SUPPORTED_TOKEN_EXCHANGE_STRATEGIES = (
    "Expirio",
    "KeycloakBroker",
    "Rfc8693",
    "ClientCredentials",
    "Introspection",
)


def get_default_token_exchange_targets():
    """Return default TokenExchangeTargets template (disabled / general deployment)."""
    return [
        {
            "Name": "idp",
            "IsEnabled": False,
            "Strategy": "KeycloakBroker",
            "Authority": "",
            "ClientId": "heappe",
            "ClientSecret": "",
            "BrokerAlias": "target-idp",
            "IntrospectSubjectToken": False,
            "IntrospectionAuthority": "",
            "IntrospectionEndpoint": "",
            "IntrospectionClientId": "",
            "IntrospectionClientSecret": "",
            "SubjectTokenSource": "incoming",
            "StoreAs": "idp",
            "AutoExchange": True,
            "AutoExchangePhase": "PreAuth"
        },
        {
            "Name": "sshca",
            "IsEnabled": False,
            "Strategy": "Rfc8693",
            "ClientId": "",
            "ClientSecret": "",
            "Audience": "ssh-ca-service",
            "SubjectTokenSource": "idp",
            "AutoExchange": True,
            "AutoExchangePhase": "PostAuth",
            "AutoExchangeCondition": "SshCaSettings:UseCertificateAuthorityForAuthentication"
        },
        {
            "Name": "userorg",
            "IsEnabled": False,
            "Strategy": "Rfc8693",
            "ClientId": "",
            "ClientSecret": "",
            "Audience": "userorg-service",
            "SubjectTokenSource": "idp",
            "AutoExchange": True,
            "AutoExchangePhase": "PostAuth"
        }
    ]


def get_efp_token_exchange_targets(
        lexis_client_id: str = "<LEXIS_KEYCLOAK_CLIENT_ID>",
        lexis_client_secret: str = "<LEXIS_KEYCLOAK_CLIENT_SECRET>",
        fip_authority: str = "https://aai.my-eurohpc.eu/proxy",
        fip_client_id: str = "<FIP_CLIENT_ID>",
        fip_client_secret: str = "<FIP_CLIENT_SECRET>",
        fip_audience: str = "<FIP_AUDIENCE>"):
    """Return EFP TokenExchangeTargets template (LEXIS Introspection -> Expirio -> FIP -> SSH CA)."""
    return [
        {
            "Name": "idp",
            "IsEnabled": True,
            "Strategy": "Expirio",
            "ExpirioProviderName": "efp",
            "ExpirioClientName": "",
            "IntrospectSubjectToken": True,
            "IntrospectionAuthority": "https://lexis/auth/realms/LEXIS_AAI",
            "IntrospectionEndpoint": "",
            "IntrospectionClientId": lexis_client_id,
            "IntrospectionClientSecret": lexis_client_secret,
            "SubjectTokenSource": "incoming",
            "StoreAs": "idp",
            "AutoExchange": True,
            "AutoExchangePhase": "PreAuth",
            "ConnectionTimeoutSeconds": 15
        },
        {
            "Name": "sshca",
            "IsEnabled": True,
            "Strategy": "Rfc8693",
            "Authority": fip_authority,
            "ClientId": fip_client_id,
            "ClientSecret": fip_client_secret,
            "GrantType": "urn:ietf:params:oauth:grant-type:token-exchange",
            "SubjectTokenType": "urn:ietf:params:oauth:token-type:access_token",
            "Audience": fip_audience,
            "SubjectTokenSource": "idp",
            "StoreAs": "sshca",
            "AutoExchange": True,
            "AutoExchangePhase": "PostAuth",
            "AutoExchangeCondition": "SshCaSettings:UseCertificateAuthorityForAuthentication",
            "ConnectionTimeoutSeconds": 15
        },
        {
            "Name": "userorg",
            "IsEnabled": False,
            "Strategy": "Rfc8693",
            "ClientId": "",
            "ClientSecret": "",
            "Audience": "userorg-service",
            "SubjectTokenSource": "idp",
            "StoreAs": "userorg",
            "AutoExchange": True,
            "AutoExchangePhase": "PostAuth",
            "ConnectionTimeoutSeconds": 15
        }
    ]


def generate_appsettings_v6_6_0(
        instance_name: str,
        sa_password: str,
        port: int = 5000,
        automigrate: bool = True,
        version: str = None,
        deployed_ip: str = None,
        efp: bool = False):
    ver_str = version or "v6.6.0"
    appsettings = generate_appsettings_v6_5_0(
        instance_name, sa_password, port, automigrate, ver_str, deployed_ip
    )

    # 1. Version Bump in ApplicationAPISettings
    if 'ApplicationAPISettings' not in appsettings:
        appsettings['ApplicationAPISettings'] = {}
    if 'DeploymentSettings' not in appsettings['ApplicationAPISettings']:
        appsettings['ApplicationAPISettings']['DeploymentSettings'] = {}
    appsettings['ApplicationAPISettings']['DeploymentSettings']['Version'] = ver_str

    if 'SwaggerDocSettings' not in appsettings['ApplicationAPISettings']:
        appsettings['ApplicationAPISettings']['SwaggerDocSettings'] = {}
    appsettings['ApplicationAPISettings']['SwaggerDocSettings']['Description'] = f"HEAppE middleware API {ver_str}"

    # 2. Update UserOrg V2 Endpoints in ExternalAuthenticationSettings.LexisAuthenticationConfiguration
    if 'ExternalAuthenticationSettings' in appsettings:
        ext_auth = appsettings['ExternalAuthenticationSettings']
        if 'LexisAuthenticationConfiguration' in ext_auth:
            lexis_auth = ext_auth['LexisAuthenticationConfiguration']
            lexis_auth['ExtendedUserInfoEndpoint'] = "/api/UserInfo/Extended"
            lexis_auth['ExtendedUserInfoV2Endpoint'] = "/api/v2/UserInfo/Extended"
            lexis_auth['CommandTemplatePermissions'] = "/api/Heappe/CommandTemplatePermissions/"
            lexis_auth['CommandTemplatePermissionsV2Endpoint'] = "/api/Heappe/CommandTemplatePermissions/"

    # 3. MigrationSettings root section
    migration_settings = appsettings.pop('MigrationSettings', None) or {
        "EncryptionKey": ""
    }

    # 4. Extend JwtTokenIntrospectionConfiguration.LexisTokenFlowConfiguration
    if 'JwtTokenIntrospectionConfiguration' not in appsettings:
        appsettings['JwtTokenIntrospectionConfiguration'] = {}
    jwt_cfg = appsettings['JwtTokenIntrospectionConfiguration']
    if efp:
        jwt_cfg['LexisTokenFlowConfiguration'] = {
            "IsEnabled": True,
            "UseExpirioServiceForTokenExchange": True,
            "IntrospectLexisToken": True,
            "Authority": "",
            "IntrospectionEndpoint": "",
            "BaseUrl": "https://lexis/auth",
            "Realm": "LEXIS_AAI",
            "Broker": "EFP",
            "Scope": "openid profile email audience",
            "PollIntervalSeconds": 5,
            "ClientId": "<LEXIS_KEYCLOAK_CLIENT_ID>",
            "ClientSecret": "<LEXIS_KEYCLOAK_CLIENT_SECRET>",
            "ConnectionTimeoutInSeconds": 15
        }
    else:
        jwt_cfg['LexisTokenFlowConfiguration'] = {
            "IsEnabled": False,
            "UseExpirioServiceForTokenExchange": True,
            "IntrospectLexisToken": False,
            "Authority": "",
            "IntrospectionEndpoint": "",
            "BaseUrl": "",
            "Realm": "",
            "Broker": "",
            "Scope": "openid profile email",
            "PollIntervalSeconds": 5,
            "ClientId": "heappe",
            "ClientSecret": "",
            "ConnectionTimeoutInSeconds": 15
        }

    # 5. Add Root Section TokenExchangeTargets & position MigrationSettings next to DatabaseMigrationSettings
    token_exchange_targets = (
        get_efp_token_exchange_targets()
        if efp
        else get_default_token_exchange_targets()
    )

    ordered_appsettings = {}
    for k, v in appsettings.items():
        if k == 'TokenExchangeTargets':
            continue
        ordered_appsettings[k] = v
        if k == 'DatabaseMigrationSettings':
            ordered_appsettings['MigrationSettings'] = migration_settings
        elif k == 'JwtTokenIntrospectionConfiguration':
            ordered_appsettings['TokenExchangeTargets'] = token_exchange_targets

    if 'MigrationSettings' not in ordered_appsettings:
        ordered_appsettings['MigrationSettings'] = migration_settings
    if 'TokenExchangeTargets' not in ordered_appsettings:
        ordered_appsettings['TokenExchangeTargets'] = token_exchange_targets

    return ordered_appsettings


def generate_appsettings_efp_v6_6_0(
        instance_name: str,
        sa_password: str,
        port: int = 5000,
        automigrate: bool = True,
        version: str = None,
        deployed_ip: str = None):
    return generate_appsettings_v6_6_0(
        instance_name=instance_name,
        sa_password=sa_password,
        port=port,
        automigrate=automigrate,
        version=version or "v6.6.0",
        deployed_ip=deployed_ip,
        efp=True
    )


def generate_appsettings_data_staging_v6_6_0(
        instance_name: str,
        sa_password: str,
        data_staging_token: str,
        port: int = 5001,
        version: str = None):
    return generate_appsettings_data_staging_v6_5_0(
        instance_name, sa_password, data_staging_token, port, version or "v6.6.0"
    )