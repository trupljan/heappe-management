# Dokumentace View a Stránek v HEAppE Management

Tento dokument poskytuje detailní analýzu a dokumentaci všech stránek (views) a funkcionalit v administrativní webové aplikaci **HEAppE Management** (postavené na frameworku Django). Dokument popisuje účel každé stránky, možné akce, které na ní může uživatel provádět, a vysvětluje logiku a pozadí jednotlivých operací v kontextu middleware HEAppE.

---

## Obsah
1. [Hlavní panel (Dashboard)](#1-hlavní-panel-dashboard)
2. [Autentizace a Uživatelský profil](#2-autentizace-a-uživatelský-profil)
3. [Správa instancí HEAppE (Instance Credentials)](#3-správa-instancí-heappe-instance-credentials)
4. [Výpočetní clustery (Clusters)](#4-výpočetní-clustery-clusters)
5. [Fronty a Skupiny front (Queues & Queue Groups)](#5-fronty-a-skupiny-front-queues--queue-groups)
6. [Projekty (Projects)](#6-projekty-projects)
7. [Šablony příkazů (Command Templates)](#7-šablony-příkazů-command-templates)
8. [Účetnictví a Alokace zdrojů (Accounting)](#8-účetnictví-a-alokace-zdrojů-accounting)
9. [Externí uživatelé (Adaptor Users)](#9-externí-uživatelé-adaptor-users)
10. [Správa nasazení a Telemetrie (Deployments & Telemetry)](#10-správa-nasazení-a-telemetrie-deployments--telemetry)
11. [Logy a Jaeger Tracing](#11-logy-a-jaeger-tracing)
12. [Zálohování a Migrační balíčky (Backups & Migration)](#12-zálohování-a-migrační-balíčky-backups--migration)
13. [Správa administrátorů a Dešifrování (Admin Users & Decrypt)](#13-správa-administrátorů-a-dešifrování-admin-users--decrypt)

---

## 1. Hlavní panel (Dashboard)
- **URL cesta:** `/dashboard/`, `/home/`, `/`
- **Třída/Funkce:** `views.dashboard_view`
- **Šablona:** `dashboard.html`

### Popis a účel
Hlavní panel slouží jako centrální bod pro monitorování stavu a zdraví aktuálně vybrané instance HEAppE. Poskytuje přehled o všech klíčových entitách (clustery, projekty, fronty, skupiny front), zobrazuje statistiky úloh a umožňuje detailně vyhledávat v historii spuštěných úloh.

### Co je možné dělat a proč
- **Zobrazení stavu zdraví (Health Check):** Zobrazuje stav z middleware API (`heappe_health_get`). Pokud API neodpovídá nebo hlásí chybu, panel zobrazí chybovou zprávu. To je kritické pro okamžité zjištění, zda je middleware funkční.
- **Upozornění na aktualizace (Middleware Update Banner):** Na pozadí se porovnává lokálně nasazená verze HEAppE (buď z API, nebo z `appsettings.json`) s nejnovějšími tagy z oficiálního GitHub repozitáře HEAppE. Pokud je k dispozici nová verze, zobrazí se varovný banner.
- **Statistiky úloh (Job Stats):** Zobrazuje agregované počty úloh v jednotlivých stavech (např. *Configuring, Submitted, Queued, Running, Finished, Failed, Canceled*). Pomáhá administrátorovi rychle identifikovat např. nahromadění úloh ve frontě nebo vysokou chybovost.
- **Detailní přehled úloh (Detailed Job Report):**
  - Umožňuje filtrovat úlohy podle časového rozsahu (s omezením na maximálně 90 dní z důvodu ochrany před přetížením databáze).
  - Obsahuje stránkovaný (paginovaný) seznam jednotlivých úloh.
  - Administrátor může v seznamu vyhledávat konkrétní úlohy.

---

## 2. Autentizace a Uživatelský profil
- **URL cesty:** `/login/`, `/logout/`, `/profile/`, `/profile/generate-session-code/`, `/reconnect/`
- **Funkce:** `views.login_view`, `views.logout_view`, `views.profile_view`, `views.generate_session_code_view`, `views.reconnect_view`
- **Šablony:** `login.html`, `user_profile.html`

### Popis a účel
Zajišťuje přihlašování administrátorů do rozhraní a správu jejich lokálního profilu. K ověřování uživatelů se používá vlastní backend `HeappeAuthBackend`, který ukládá přihlašovací údaje do relace (session) k autorizaci API požadavků vůči HEAppE middleware.

### Co je možné dělat a proč
- **Přihlášení a odhlášení:** Uživatel zadává přihlašovací údaje, které se ověřují vůči HEAppE instanci. Po přihlášení se získá `SessionCode`, který se používá pro všechny následné API volání. Při odhlášení se relace bezpečně vymaže.
- **Změna profilu:** Umožňuje změnit lokální uživatelské jméno, e-mail a heslo pro přístup do tohoto administračního panelu (Django uživatel).
- **Obnovení spojení (Reconnect / Generate Session Code):** Pokud vyprší platnost tokenu (`SessionCode`) na straně HEAppE middleware, může si administrátor kliknutím na reconnect vygenerovat nový session kód, aniž by se musel kompletně odhlašovat a znovu zadávat přihlašovací údaje.

---

## 3. Správa instancí HEAppE (Instance Credentials)
- **URL cesty:** 
  - `/instances/` (Seznam instancí)
  - `/instances/create/` (Vytvoření nové instance)
  - `/instances/<id>/edit/` (Úprava instance)
  - `/instances/<id>/delete/` (Smazání instance)
  - `/instances/<id>/choose/` (Výběr aktivní instance)
  - `/chose-instance/` (Zjednodušený výběr instance)
- **Funkce:** `views.instance_credentials_list`, `views.instance_credentials_create`, `views.instance_credentials_edit`, `views.instance_credentials_delete`, `views.chose_instance_view`
- **Šablony:** `instance_credentials.html`, `instance_credentials_form.html`, `chose_instances.html`

### Popis a účel
Tato sekce umožňuje spravovat přihlašovací údaje a konfigurační parametry k jednotlivým instancím HEAppE middleware (např. vývojová, testovací, produkční). Administrátor může definovat hostitelskou adresu, přístupové údaje administrátora HEAppE a konfigurovat připojení k logovací databázi (MS SQL) pro danou instanci.

### Co je možné dělat a proč
- **Správa instancí (CRUD):** Umožňuje přidávat, upravovat a mazat záznamy o instancích (adresy a šifrovaná hesla). Hromadné mazání (bulk delete) pomáhá při čištění nepoužívaných instancí.
- **Výběr aktivní instance:** Přepíná kontext aplikace na konkrétní instanci. Po výběru se vyčistí předchozí session data a uživatel je vyzván k nové autentizaci vůči vybrané instanci. To umožňuje spravovat více nezávislých HEAppE middleware z jednoho rozhraní.
- **Konfigurace logovací databáze:** Pro každou instanci lze uložit parametry MS SQL serveru, kde HEAppE ukládá své interní logy. To je nutné pro to, aby fungoval integrovaný [Prohlížeč systémových logů](#11-logy-a-jaeger-tracing).

---

## 4. Výpočetní clustery (Clusters)
- **URL cesty:**
  - `/clusters/` (Seznam clusterů)
  - `/clusters/new/` (Vytvoření clusteru)
  - `/clusters/<id>/` nebo `/clusters/<id>/<tab>` (Detail clusteru s kartami)
  - `/clusters/<id>/delete/` (Smazání clusteru)
  - `/clusters/setup-slurm/` (API pro nasazení simulátoru Slurm)
  - `/clusters/setup-slurm-status/` (Stav nasazení simulátoru Slurm)
- **Funkce:** `views.cluster_list`, `views.cluster_create`, `views.cluster_detail`, `views.cluster_delete`, `views.setup_slurm_view`, `views.setup_slurm_status_view`
- **Šablony:** `clusters.html`, `cluster_detail.html`

### Popis a účel
Výpočetní clustery jsou základní hardwarovou infrastrukturou spravovanou HEAppE middlewarem. Uživatelé na nich spouštějí své úlohy. Tyto views umožňují kompletní konfiguraci clusterů a jejich integraci.

### Co je možné dělat a proč
- **Seznam clusterů:** Zobrazuje tabulku všech registrovaných clusterů včetně informací o plánovači (Scheduler) a protokolu připojení. Podporuje hromadné mazání.
- **Vytvoření a Úprava clusteru (Karta *Detail*):**
  - Nastavení názvu, popisu, hlavního uzlu (MasterNodeName), časového pásma, portu a doménového jména.
  - Výběr plánovače (např. *Slurm, PBS, FirecREST*) a přenosového protokolu.
  - **Custom Configuration (JSON):** Umožňuje uložit dodatečnou specifickou konfiguraci (pro novější verze HEAppE 6.4.0+). Např. pro plánovač *FirecREST* je nutné v JSON specifikovat klíče `IdpUrl` / `ExpirioSecretName` a `HomeDirectoryTemplate`.
- **Správa metod přenosu souborů (Karta *Detail* - File Transfer Methods):**
  - Clustery vyžadují definování metod pro přenos vstupních/výstupních dat (např. *SFTP, SCP*).
  - Lze přidávat, upravovat a mazat jednotlivé přenosové uzly (Hostname, Protokol, Port).
- **Správa proxy připojení (Karta *Proxy connections*):**
  - Umožňuje definovat a přiřazovat SOCKS4, SOCKS5 nebo HTTP proxy servery, přes které má HEAppE komunikovat s výpočetním clusterem (vhodné pro bezpečné sítě bez přímého internetového přístupu).
- **Prohlížení front a projektů (Karty *Queues* a *Projects*):**
  - Umožňuje vidět, jaké fronty (výpočetní uzly/partitiony) jsou na clusteru dostupné a které projekty mají na tento cluster přístup. Administrátor může z této karty hromadně odebírat (odpřiřazovat) projekty z clusteru.
- **Simulátor Slurm (Setup Slurm Simulator):**
  - Umožňuje jedním kliknutím nasadit testovací instanci simulátoru plánovače Slurm v Docker kontejneru na serveru.
  - Skript vygeneruje unikátní konfiguraci, nastaví Munge autentizaci, nainstaluje a nakonfiguruje MariaDB pro účtování Slurm a spustí procesy `slurmctld`, `slurmd` a `slurmdbd`. 
  - To je extrémně užitečné pro testování chování HEAppE middleware vůči clusteru v izolovaném prostředí bez nutnosti přístupu ke skutečnému superpočítači.

---

## 5. Fronty a Skupiny front (Queues & Queue Groups)
- **URL cesty:**
  - `/queues/` (Seznam front)
  - `/queues/new/<cluster_id>` (Vytvoření nové fronty)
  - `/queues/<id>/` (Detail fronty)
  - `/queues/<id>/delete/` (Smazání fronty)
  - `/queue-groups/` (Seznam skupin front)
  - `/queue-groups/new/` (Vytvoření skupiny front)
  - `/queue-groups/<id>/` (Detail skupiny front)
  - `/queue-groups/<id>/modify/` (Úprava skupiny front)
- **Funkce:** `views.queues_view`, `views.queue_create`, `views.queue_detail`, `views.queue_delete`, `views.queue_groups`, `views.queue_group_detail`, `views.queue_group_create`, `views.queue_group_modify`, `views.assign_formula`/`unassign_formula`/`add_formula`/`edit_formula`
- **Šablony:** `queues.html`, `queue_detail.html`, `create_queue.html`, `queue_groups.html`, `queue_group_detail.html`, `create_queue_group.html`

### Popis a účel
Fronty (v datovém modelu HEAppE jako *Cluster Node Types*) reprezentují konkrétní hardwarové partitiony nebo typy uzlů na výpočetním clusteru (např. uzly s GPU, uzly s velkou pamětí). Skupiny front (*Cluster Node Type Aggregations*) sdružují tyto fronty pro účely limitování a účtování spotřeby.

### Co je možné dělat a proč
- **Správa front (Node Types):** Umožňuje definovat hardwarové parametry fronty (počet jader na uzel, velikost paměti, maximální počet uzlů, maximální délku běhu úlohy v sekundách atd.) a namapovat je na konkrétní metodu přenosu souborů.
- **Správa skupin front (Aggregations):**
  - Umožňuje logicky seskupit různé fronty (např. napříč clustery) a sledovat jejich celkové čerpání uživateli.
  - **Výpočetní vzorce (Formulas):** Ke skupinám front lze přiřazovat matematické vzorce pro výpočet ceny spotřebovaného času (např. různé koeficienty pro GPU vs. CPU uzly). Administrátor může vzorce přidávat, upravovat a mazat.
  - **Přiřazování projektů:** Umožňuje spravovat, které projekty mohou danou skupinu front využívat.

---

## 6. Projekty (Projects)
- **URL cesty:**
  - `/projects/` (Seznam projektů)
  - `/projects/new/` (Vytvoření projektu)
  - `/projects/<id>/` (Detail projektu s kartami)
  - `/projects/assign/` (Přiřazení projektu ke clusteru)
  - `/projects/unassign/<id>` (Zrušení přiřazení)
- **Funkce:** `views.project_list`, `views.project_create`, `views.project_detail`, `views.project_assign_to_cluster`, `views.delete_assignment`, `views.project_update`
- **Šablony:** `projects.html`, `project_detail.html`, `assign_project_to_cluster.html`

### Popis a účel
Projekty v HEAppE slouží jako organizační jednotky. Uživatelé spouštějí úlohy pod hlavičkou konkrétního projektu, který definuje jejich oprávnění, přístup ke clusterům a diskovým úložištím.

### Co je možné dělat a proč
- **Správa projektů:** Založení nového projektu s názvem, popisem a datem platnosti (od-do).
- **Přiřazení ke clusteru:**
  - Definuje, na kterých clusterech může projekt běžet.
  - **Nastavení cest k úložištím:** Při přiřazení se specifikují absolutní cesty na clusteru pro:
    - *Scratch storage:* Rychlé dočasné úložiště pro běžící výpočty.
    - *Permanent storage:* Dlouhodobé osobní úložiště uživatele.
    - *Project storage:* Úložiště sdílené všemi členy projektu.
- **HPC Accounts (Karta *HPC Accounts*):**
  - HEAppE potřebuje fyzické systémové účty na cílových clusterech, pod kterými spouští úlohy.
  - Umožňuje inicializovat HPC účet, vytvořit nový lokální účet, přejmenovat jej, smazat nebo **regenerovat SSH klíč** používaný pro bezheslový přístup.
  - Obsahuje možnost otestovat připojení a ověřit oprávnění k zápisu/čtení na clusteru (HPC access test).
- **Testování spouštění úloh (Test Job Submission):**
  - Přímo z detailu projektu (nebo přes šablonu příkazů) lze odeslat zkušební úlohu na cluster (`submit_job_view`).
  - Umožňuje monitorovat stav této úlohy (`job_status_view`), stahovat její výstupní soubory (`download_job_file_view`) a sledovat její detaily v reálném čase (`job_live_details_partial`). To je klíčové pro ověření správnosti integrace clusteru.

---

## 7. Šablony příkazů (Command Templates)
- **URL cesty:**
  - `/command-templates/<project_id>/new/` (Vytvoření šablony)
  - `/command-templates/<id>/` (Detail šablony)
  - `/command-templates/<id>/modify/` (Úprava šablony)
  - `/command-templates/<id>/delete/` (Smazání šablony)
- **Funkce:** `views.command_template_create`, `views.command_template_detail`, `views.command_template_modify`, `views.command_template_delete`, `views.add_parameter_to_command_template`/`update_parameter_in_command_template`/`delete_parameter_from_command_template`
- **Šablony:** `command_template_detail.html`, `create_command_template.html`

### Popis a účel
Šablona příkazů definuje aplikaci nebo skript, který se má na HPC clusteru spustit (např. spustitelný soubor, výchozí parametry, proměnné prostředí). Uživatelé pak při vytváření úloh pouze odkazují na tuto šablonu a specifikují své parametry.

### Co je možné dělat a proč
- **Správa šablon:** Konfigurace spustitelného souboru (Executable File), šablony příkazového řádku a přiřazených front, na kterých může šablona běžet.
- **Správa parametrů šablony (Parameters):**
  - Umožňuje definovat jednotlivé argumenty programu (např. cesty k datům, číselné hodnoty).
  - Lze nastavit název parametru, popis, výchozí hodnotu a zda je parametr povinný. Administrátor může parametry přidávat, měnit a mazat.

---

## 8. Účetnictví a Alokace zdrojů (Accounting)
- **URL cesta:** `/accounting/<project_id>`
- **Funkce:** `views.accounting_view`, `views.assign_queue_group_to_project`, `views.unassign_queue_group_from_project`
- **Šablona:** `accounting.html`

### Popis a účel
Tato stránka slouží k nastavení limitů a sledování spotřeby výpočetního času pro konkrétní projekt. Integruje skupiny front a jejich účtovací záznamy.

### Co je možné dělat a proč
- **Alokace skupin front k projektu:**
  - Administrátor může k projektu přiřadit vybranou skupinu front a definovat **alokační limit** (např. kolik Node-Hodin může projekt celkově vyčerpat).
  - **Sledování aktivního účetnictví:** Systém na základě aktuálního data vyhodnocuje, které účtovací období (Accounting) je pro danou skupinu aktivní, a zobrazuje jeho čerpání.
- **Odpřiřazení skupiny front:** Odebere limit a přístup projektu k dané skupině zdrojů.

---

## 9. Externí uživatelé (Adaptor Users)
- **URL cesty:**
  - `/manage-external-users/` nebo `/manage-external-users/<project_id>/`
  - `/adaptor_users/new/` (Vytvoření nového uživatele)
  - `/adaptor_users/<username>/` (Detail uživatele)
  - `/adaptor_users/assign/<username>/` (Přiřazení k projektu)
  - `/adaptor_users/unassign/<username>/` (Odebrání z projektu)
- **Funkce:** `views.manage_project_adaptor_users`, `views.adaptor_user_create`, `views.adaptor_user_detail`, `views.adaptor_user_assign_to_project`, `views.adaptor_user_unassign_from_project`
- **Šablony:** `manage_project_users.html`, `adaptor_user_detail.html`, `create_adaptor_user.html`

### Popis a účel
Adaptor Users jsou koncoví uživatelé (výzkumníci, klienti), kteří přistupují k HEAppE middleware přes API k odesílání svých výpočetních úloh. Tato rozhraní spravují jejich uživatelské účty a jejich role v rámci projektů.

### Co je možné dělat a proč
- **Správa uživatelských účtů (CRUD):** Založení nového uživatele v databázi HEAppE a správa jeho hesel.
- **Správa členství v projektech (Projektové role):**
  - Umožňuje přiřadit uživatele k vybranému projektu pod konkrétní rolí:
    1. *Project Administrator (Role ID 1):* Správa nastavení projektu.
    2. *Standard User (Role ID 2):* Spouštění úloh v rámci projektu.
    3. *Auditor (Role ID 3):* Pouze čtení a monitoring úloh.
  - Zajišťuje bezpečné oddělení přístupových práv k výpočetním zdrojům.

---

## 10. Správa nasazení a Telemetrie (Deployments & Telemetry)
- **URL cesty:**
  - `/deploy/` nebo `/deploy/<instance_name>/` (Správa nasazení instance)
  - `/deploy/<instance_name>/config/` (Úprava konfigurace `appsettings.json`)
  - `/deploy/<instance_name>/update-status/` (API pro akce docker-compose)
  - `/deploy/<instance_name>/telemetry/toggle/` (Přepnutí telemetrie)
  - `/api/deploy-direct/` (Spuštění celkového instalačního skriptu)
  - `/fetch-branches/` (Získání větví z repozitáře)
- **Funkce:** `views.deploy_view`, `views.instance_config_view`, `views.update_status_view`, `views.toggle_telemetry_view`, `views.trigger_deployment_direct`, `views.fetch_repo_branches`
- **Šablony:** `deploy_viewer.html`, `instance_config.html`

### Popis a účel
Tato sekce umožňuje spravovat fyzické nasazení instancí HEAppE middleware na serveru. Využívá technologii Docker Compose a umožňuje vzdáleně spouštět, zastavovat, aktualizovat a konfigurovat jednotlivé kontejnery HEAppE (API, DB, Jaeger atd.).

### Co je možné dělat a proč
- **Nasazení nové / existující instance:**
  - Umožňuje vybrat Git URL a větev/tag a spustit na pozadí instalační bash skript `deploy.sh` (`trigger_deployment_direct`). Uživatel vidí průběh instalace.
- **Docker Compose Ovládání (Kontejnerové akce):**
  - Administrátor může spouštět akce jako *Start, Stop, Restart, Rebuild, Update* buď globálně pro celou instanci, nebo selektivně pro jednotlivé kontejnery (např. pouze pro API kontejner).
  - Zobrazuje stav kontejnerů (Running, Exited, atd.) a namapované porty.
- **Konfigurace instance (`appsettings.json`):**
  - Umožňuje přímo v prohlížeči upravovat hlavní konfigurační soubor HEAppE middleware a následně restartovat kontejnery pro aplikování změn.
- **Správa telemetrie:** Přepínač pro zapnutí/vypnutí sběru telemetrických dat (např. Jaeger, OpenTelemetry).

---

## 11. Logy a Jaeger Tracing
- **URL cesty:**
  - `/logs/` (Prohlížeč logů z databáze)
  - `/logs/context/` (API pro kontextové logy)
  - `/logs/<container_id>/` (Prohlížeč logů z Docker souborů)
  - `/fetch-new-logs/` (API pro načítání nových řádků logů)
  - `/jaeger/` (Jaeger Native Page)
  - `/jaeger-proxy/` (Proxy pro Jaeger požadavky)
- **Funkce:** `views.logs_view`, `views.logs_context_api`, `views.container_logs_view`, `views.fetch_new_logs`, `views.jaeger_page`, `views.jaeger_proxy`, `views.stream_logs`
- **Šablony:** `logs.html`, `file_log_viewer.html`, `jaeger.html`

### Popis a účel
Nástroje pro diagnostiku chyb a analýzu výkonu HEAppE middleware. Kombinují prohlížení strukturovaných logů z SQL databáze, surových logovacích souborů na disku a trasování API požadavků pomocí Jaegeru.

### Co je možné dělat a proč
- **SQL Log Prohlížeč (`logs_view`):**
  - Načítá logy z MS SQL databáze nakonfigurované u dané instance.
  - Umožňuje filtrovat podle logovací úrovně (Error, Warning, Info, Debug, Critical), vyhledávat v textu zpráv a omezovat časovým obdobím.
  - Vykresluje statistické grafy četnosti chyb v čase pro rychlou diagnostiku výpadků.
- **Kontextové logy (`logs_context_api`):**
  - Kliknutím na konkrétní chybu může administrátor vyvolat "kontext" – načte se 15 logovacích záznamů, které bezprostředně předcházely chybě. To výrazně urychluje hledání příčiny problémů.
- **Docker/Souborový log prohlížeč (`log_viewer_view`):**
  - Čte surové `.log` soubory přímo z disku ze složky `/opt/heappe-deployment/<instance>/app/logs/API/`.
  - Optimalizováno pro čtení velkých souborů pozpátku (od nejnovějších řádků).
  - Podporuje **Live Streaming (SSE - Server-Sent Events)** přes endpoint `stream_logs` – logy se na stránce objevují v reálném čase, jak se zapisují na disk (vhodné při sledování průběhu chybné operace).
- **Jaeger Proxy:**
  - Integruje Jaeger UI přímo do admin panelu přes Iframe a proxy.
  - Umožňuje procházet distribuované trasování požadavků, zkoumat latenci jednotlivých volání metod a analyzovat úzká hrdla výkonu.

---

## 12. Zálohování a Migrační balíčky (Backups & Migration)
- **URL cesty:**
  - `/database-backups/` (Zálohování SQL databáze)
  - `/migration-package/` (Hlavní stránka migrace)
  - `/migration-package/export/` (Export migračního balíčku)
  - `/migration-package/import/` (Import migračního balíčku)
- **Funkce:** `views.database_backups`, `views.migration_package_view`, `views.export_migration_package`, `views.import_migration_package`
- **Šablony:** `database_backups.html`, `migration_package.html`

### Popis a účel
Tyto nástroje zajišťují kontinuitu provozu, zálohování klíčových dat a možnost snadného přenosu konfigurace mezi jednotlivými servery/instancemi. Jsou podporovány od verze HEAppE 6.4.0+.

### Co je možné dělat a proč
- **SQL Zálohování a Obnova (Database Backups):**
  - **Full Backup:** Provede kompletní zálohu relační databáze HEAppE.
  - **Transaction Logs Backup:** Záloha pouze transakčních logů pro point-in-time recovery.
  - **Restore:** Umožňuje vybrat konkrétní záložní soubor z disku a obnovit z něj databázi.
- **Migrační balíčky (Migration Packages):**
  - Umožňují exportovat kompletní nastavení HEAppE (všechny clustery, projekty, fronty, skupiny front a šablony příkazů) do jednoho binárního zašifrovaného souboru `.enc`.
  - **Bezpečnost:** Export i import vyžaduje zadání silného hesla (passphrase o délce min. 12 znaků, obsahující velká/malá písmena a speciální znaky). Heslo šifruje citlivé údaje jako hesla ke clusterům a privátní klíče.
  - **Scénář využití:** Přenášení konfigurace z testovacího prostředí do produkčního bez nutnosti ručního přepisování desítek formulářů.

---

## 13. Správa administrátorů a Dešifrování (Admin Users & Decrypt)
- **URL cesty:**
  - `/admin-users/` (Seznam lokálních administrátorů)
  - `/admin-users/create/` (Založení lokálního uživatele)
  - `/admin-users/<id>/edit/` (Úprava nastavení uživatele)
  - `/admin-users/<id>/password/` (Změna hesla uživatele)
  - `/admin-users/<id>/delete/` (Smazání uživatele)
  - `/decrypt/` (Zobrazení dešifrovaných hesel)
- **Funkce:** `views.admin_users_list`, `views.admin_users_create`, `views.admin_users_edit`, `views.admin_users_password`, `views.admin_users_delete`, `views.decrypt_credentials_view`
- **Šablony:** `admin_users_list.html`, `admin_users_form.html`, `admin_users_password.html`, `admin_users_delete_confirm.html`, `admin_users_success.html`, `decrypt_credentials.html`

### Popis a účel
Správa uživatelských účtů s přístupem do tohoto webového administračního rozhraní (Django `User` model) a nástroje pro zobrazení citlivých systémových přihlašovacích údajů. Přístup k těmto views je striktně omezen pouze pro superuživatele (`is_superuser`).

### Co je možné dělat a proč
- **Správa administrátorů (CRUD):** Založení, editace, změna hesla a smazání administrátorů rozhraní. Obsahuje pojistky proti smazání vlastního účtu nebo odebrání si superuživatelských práv.
- **Dešifrování systémových údajů (`decrypt_credentials_view`):**
  - Zobrazuje rozhraní, které umožňuje superuživatelům (po zadání dešifrovacího klíče) zobrazit citlivé údaje uložené v databázi aplikace v šifrovaném stavu (např. hesla k cílovým databázím, heppa_password k instancím).
  - Slouží k rychlému ověření uložených přihlašovacích údajů při chybách v připojení.
