use crate::api::low_level::blackboard::BlackboardUnautherizedError;

use super::*;

impl Client {
    pub async fn blackboard(
        &self,
        username: &str,
        password: &str,
        otp_code: &str,
    ) -> anyhow::Result<Blackboard> {
        let c = &self.0.http_client;
        if let Err(e) = c.bb_homepage().await {
            // expect unauthorized error
            if let Err(e) = e.downcast::<BlackboardUnautherizedError>() {
                log::error!("error during preflight: {e}");
            }
            c.bb_login(username, password, otp_code).await?;

            if let Some(path) = &self.0.cookie_restore_path {
                c.save_set_cookies(path).await?;
                log::info!("blackboard login session saved to {}", path.display());
            }
        } else {
            log::info!("reuse saved login session");
        }

        Ok(Blackboard {
            client: self.clone(),
        })
    }
}

#[derive(Debug)]
pub struct Blackboard {
    client: Client,
    // token: String,
}

impl Blackboard {
    async fn _get_courses(&self) -> anyhow::Result<Vec<CourseMetaData>> {
        let dom = self.client.bb_homepage().await?;
        let re = regex::Regex::new(r"key=([^,]+),").unwrap();
        let portlet_sel = Selector::parse("div.portlet").unwrap();
        let title_in_portlet_sel = Selector::parse("span.moduleTitle").unwrap();
        let ul_sel = Selector::parse("ul.courseListing").unwrap();
        let sel = Selector::parse("li a").unwrap();

        let to_course = |a: scraper::ElementRef<'_>, is_current: bool| {
            let href = a
                .value()
                .attr("href")
                .context("course launcher href not found")?;
            let text = normalize_text(&a.text().collect::<String>());
            let key = re
                .captures(href)
                .and_then(|s| s.get(1))
                .context("course key not found")?
                .as_str()
                .to_owned();

            Ok(CourseMetaData {
                id: key,
                long_title: text,
                is_current,
                launcher_url: href.to_owned(),
            })
        };

        // the first one contains the courses in the current semester
        // the second one contains the courses in the previous semester
        let mut courses = Vec::new();

        for portlet in dom.select(&portlet_sel) {
            let Some(title) = portlet.select(&title_in_portlet_sel).next() else {
                continue;
            };
            let title = title.text().collect::<String>();
            log::info!("scanning portlet: {title}");

            if !title.contains("课程") && !title.contains("Courses") {
                continue;
            }

            let is_current = title.contains("当前") || title.contains("Current Semester Courses");
            for ul in portlet.select(&ul_sel) {
                let items = ul
                    .select(&sel)
                    .map(|a| to_course(a, is_current))
                    .collect::<Vec<_>>();
                log::info!("found {} courses, is_current: {is_current}", items.len());
                courses.extend(items);
            }
        }

        if courses.is_empty() {
            anyhow::bail!("courses not found");
        }

        courses.into_iter().collect::<anyhow::Result<Vec<_>>>()
    }
    pub async fn get_courses(&self, only_current: bool) -> anyhow::Result<Vec<CourseHandle>> {
        log::info!("fetching courses...");

        let courses = with_cache(
            "Blackboard::_get_courses",
            self.client.cache_ttl(),
            self._get_courses(),
        )
        .await?;

        let mut courses = courses
            .into_iter()
            .map(|meta| CourseHandle {
                client: self.client.clone(),
                meta: CourseMeta::from(meta).into(),
            })
            .collect::<Vec<_>>();

        if only_current {
            courses.retain(|c| c.meta.is_current);
        }

        Ok(courses)
    }
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
struct CourseMetaData {
    id: String,
    long_title: String,
    /// 是否是当前学期的课程
    is_current: bool,
    launcher_url: String,
}

#[derive(Debug)]
pub struct CourseMeta {
    id: String,
    long_title: String,
    /// 是否是当前学期的课程
    is_current: bool,
    launcher_url: String,
}

impl From<CourseMetaData> for CourseMeta {
    fn from(value: CourseMetaData) -> Self {
        Self {
            id: value.id,
            long_title: value.long_title,
            is_current: value.is_current,
            launcher_url: value.launcher_url,
        }
    }
}

impl CourseMeta {
    pub fn id(&self) -> &str {
        &self.id
    }

    /// Full Blackboard course title as displayed in the portal.
    pub fn title(&self) -> &str {
        self.long_title
            .split_once(':')
            .map(|(_, title)| title.trim())
            .filter(|title| !title.is_empty())
            .unwrap_or(self.long_title.trim())
    }

    /// Short course name without a trailing semester marker when present.
    pub fn name(&self) -> &str {
        let s = self.title();
        s.char_indices()
            .rfind(|(_, c)| *c == '(' || *c == '（')
            .map(|(i, _)| s[..i].trim())
            .filter(|name| !name.is_empty())
            .unwrap_or(s)
    }

    pub fn is_current(&self) -> bool {
        self.is_current
    }

    pub fn launcher_url(&self) -> &str {
        &self.launcher_url
    }
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseMenuItem {
    pub label: String,
    pub url: String,
}

#[derive(Debug, Clone)]
pub struct CourseHandle {
    client: Client,
    meta: Arc<CourseMeta>,
}

impl CourseHandle {
    pub fn meta(&self) -> &CourseMeta {
        &self.meta
    }

    pub async fn _get(&self) -> anyhow::Result<Vec<CourseMenuItem>> {
        let dom = match self
            .client
            .bb_page_by_uri_follow_redirects(self.meta.launcher_url())
            .await
        {
            Ok(dom) => dom,
            Err(err) => {
                log::warn!(
                    "launcher page failed for {}: {err:#}; fallback to course page",
                    self.meta.id()
                );
                self.client.bb_coursepage(&self.meta.id).await?
            }
        };

        let entries = dom
            .select(
                &Selector::parse(
                    "#courseMenuPalette_contents > li > a, #courseMenuPalette_contents a",
                )
                .unwrap(),
            )
            .filter_map(|a| {
                let label = normalize_text(&a.text().collect::<String>());
                let href = a.value().attr("href")?.to_owned();
                (!label.is_empty()).then_some(CourseMenuItem { label, url: href })
            })
            .collect::<Vec<_>>();

        if entries.is_empty() {
            anyhow::bail!("course menu not found for {}", self.meta.id());
        }

        Ok(entries)
    }

    pub async fn get(&self) -> anyhow::Result<Course> {
        log::info!("fetching course {}", self.meta.title());

        let menu = with_cache(
            &format!("CourseHandle::_get_{}", self.meta.id),
            self.client.cache_ttl(),
            self._get(),
        )
        .await?;

        let entries = menu
            .iter()
            .map(|item| (item.label.clone(), item.url.clone()))
            .collect::<HashMap<_, _>>();

        Ok(Course {
            client: self.client.clone(),
            meta: self.meta.clone(),
            entries,
            menu,
        })
    }
}

#[derive(Debug, Clone)]
pub struct Course {
    client: Client,
    meta: Arc<CourseMeta>,
    entries: HashMap<String, String>,
    menu: Vec<CourseMenuItem>,
}

impl Course {
    pub fn client(&self) -> &Client {
        &self.client
    }

    pub fn meta(&self) -> &CourseMeta {
        &self.meta
    }

    #[allow(dead_code)]
    pub fn get_menu(&self) -> &[CourseMenuItem] {
        &self.menu
    }

    pub fn find_menu_item(&self, label: &str) -> Option<&CourseMenuItem> {
        self.menu
            .iter()
            .find(|item| item.label.contains(label) || label.contains(&item.label))
    }

    pub fn content_stream(&self) -> CourseContentStream {
        CourseContentStream::new(
            self.client.clone(),
            self.meta.clone(),
            self.entries()
                .iter()
                .filter_map(|(_, uri)| {
                    let url = low_level::convert_uri(uri).ok()?.into_url().ok()?;
                    if !low_level::blackboard::LIST_CONTENT.ends_with(url.path()) {
                        return None;
                    }

                    let (_, content_id) = url.query_pairs().find(|(k, _)| k == "content_id")?;

                    Some(content_id.to_string())
                })
                .collect(),
        )
    }

    pub fn build_content(&self, data: CourseContentData) -> CourseContent {
        CourseContent {
            client: self.client.clone(),
            course: self.meta.clone(),
            data: data.into(),
        }
    }

    pub fn entries(&self) -> &HashMap<String, String> {
        &self.entries
    }
    #[allow(dead_code)]
    pub async fn query_launch_link(&self, uri: &str) -> anyhow::Result<String> {
        let res = self.client.get_by_uri(uri).await?;
        let st = res.status();
        anyhow::ensure!(st.as_u16() == 302, "invalid status: {}", st);
        let loc = res
            .headers()
            .get("location")
            .context("location header not found")?
            .to_str()
            .context("location header not str")?
            .to_owned();

        Ok(loc)
    }
    pub async fn get_video_list(&self) -> anyhow::Result<Vec<CourseVideoHandle>> {
        log::info!("fetching video list for course {}", self.meta.title());

        let videos = with_cache(
            &format!("Course::get_video_list_{}", self.meta.id),
            self.client.cache_ttl(),
            self._get_video_list(),
        )
        .await?;

        let videos = videos
            .into_iter()
            .map(|meta| {
                Ok(CourseVideoHandle {
                    client: self.client.clone(),
                    meta: meta.into(),
                    course: self.meta.clone(),
                })
            })
            .collect::<anyhow::Result<Vec<_>>>()?;

        Ok(videos)
    }
    async fn _get_video_list(&self) -> anyhow::Result<Vec<CourseVideoMeta>> {
        let u = low_level::blackboard::VIDEO_LIST.into_url()?;
        let dom = self.client.bb_course_video_list(&self.meta.id).await?;

        let videos = dom
            .select(&Selector::parse("tbody#listContainer_databody > tr").unwrap())
            .map(|tr| {
                let title = tr
                    .child_elements()
                    .nth(0)
                    .unwrap()
                    .text()
                    .collect::<String>();
                let s = Selector::parse("span.table-data-cell-value").unwrap();
                let mut values = tr.select(&s);
                let time = values
                    .next()
                    .context("time not found")?
                    .text()
                    .collect::<String>();
                let _ = values.next().context("teacher not found")?;
                let link = values.next().context("video link not found")?;
                let a = link
                    .child_elements()
                    .next()
                    .context("video link anchor not found")?;
                let link = a
                    .value()
                    .attr("href")
                    .context("video link not found")?
                    .to_owned();

                Ok(CourseVideoMeta {
                    title,
                    time,
                    url: u.join(&link)?.to_string(),
                })
            })
            .collect::<anyhow::Result<Vec<_>>>()?;

        Ok(videos)
    }

    /// 直接从课程公告页抓取课程公告。
    pub async fn list_announcements_from_coursepage(
        &self,
    ) -> anyhow::Result<Vec<CourseAnnouncementHandle>> {
        log::info!(
            "fetching announcement list from course page for {}",
            self.meta.title()
        );

        let dom = self.client.bb_coursepage(&self.meta.id).await?;
        let container_selector =
            Selector::parse(".vtbegenerated, #content_listContainer, div.content, div.clearfix")
                .unwrap();
        let h3_selector = Selector::parse("h3").unwrap();

        let mut parsed_announcements = Vec::new();

        for container in dom.select(&container_selector) {
            let h3_elements = container.select(&h3_selector).collect::<Vec<_>>();

            if !h3_elements.is_empty() {
                for h3 in h3_elements {
                    let title = h3.text().collect::<String>().trim().to_string();

                    if title.is_empty()
                        || title.contains("课程")
                        || title.contains("学期")
                        || title == "我的小组"
                        || title == "公告"
                        || title.contains("查看选项")
                        || title.contains("菜单管理")
                    {
                        continue;
                    }

                    let mut sibling = h3.next_sibling();
                    let mut content = String::new();
                    let mut time = String::new();

                    for _ in 0..10 {
                        let Some(sib) = sibling else {
                            break;
                        };

                        if let Some(elem) = sib.value().as_element() {
                            let el_ref = scraper::ElementRef::wrap(sib).unwrap();
                            let tag = elem.name();

                            if tag == "h3" {
                                break;
                            }

                            let text = el_ref.text().collect::<String>();
                            if tag == "p" && text.contains("发布") {
                                time = text.trim().to_string();
                            } else if (tag == "div" || tag == "p") && !text.trim().is_empty() {
                                if !content.is_empty() {
                                    content.push('\n');
                                }
                                content.push_str(&text);
                            }
                        }

                        sibling = sib.next_sibling();
                    }

                    parsed_announcements.push((title, content, time));
                }
            } else {
                let content = container.text().collect::<String>().trim().to_string();
                let time = container
                    .select(&Selector::parse("p").unwrap())
                    .next()
                    .map(|el| el.text().collect::<String>().trim().to_string())
                    .unwrap_or_default();

                let lower_content = content.to_lowercase();
                if lower_content.contains("var json")
                    || lower_content.contains("查看选项")
                    || lower_content.contains("菜单管理")
                {
                    continue;
                }

                if !content.is_empty() && content.len() > 10 {
                    let title = content.chars().take(20).collect::<String>();
                    let title = if content.chars().count() > 20 {
                        format!("{title}...")
                    } else {
                        title
                    };
                    parsed_announcements.push((title, content, time));
                }
            }
        }

        let mut announcements = Vec::new();
        let mut seen_titles = HashSet::new();

        for (_idx, (title, content, time)) in parsed_announcements.iter().enumerate() {
            if title.is_empty() || title.len() < 5 {
                continue;
            }

            let course_name = self.meta.name();
            if title.starts_with(course_name) || title.contains("学期") || title == "公告" {
                continue;
            }

            let content_clean = content.trim();
            if content_clean.starts_with(course_name) && content_clean.len() < 50 {
                continue;
            }

            let dedup_key = announcement_dedup_key(title, content, time);
            if !seen_titles.insert(format!("{}:{dedup_key}", self.meta.id)) {
                continue;
            }

            let id = format!("announcement:{}", id::fnv1a64_hex(&dedup_key));
            let content_data = CourseContentData {
                id: id.clone(),
                title: title.clone(),
                kind: CourseContentKind::Announcement,
                has_link: false,
                descriptions: if !content.is_empty() {
                    content
                        .lines()
                        .map(str::trim)
                        .filter(|line| !line.is_empty())
                        .map(ToOwned::to_owned)
                        .collect()
                } else {
                    vec![]
                },
                attachments: vec![],
                time: if !time.is_empty() {
                    Some(time.clone())
                } else {
                    None
                },
            };

            announcements.push(CourseAnnouncementHandle {
                course: self.meta.clone(),
                content: Arc::new(content_data),
            });
        }

        log::info!(
            "found {} announcements for course {}",
            announcements.len(),
            self.meta.title()
        );

        Ok(announcements)
    }

    pub async fn get_contents_tree(
        &self,
        root_content_id: Option<&str>,
    ) -> anyhow::Result<CourseContentsTree> {
        let (root_label, root_content_id, root_url) = if let Some(root_content_id) = root_content_id
        {
            (
                "教学内容".to_owned(),
                root_content_id.to_owned(),
                format!(
                    "/webapps/blackboard/content/listContent.jsp?course_id={}&content_id={}",
                    self.meta.id(),
                    root_content_id
                ),
            )
        } else {
            let item = self.find_menu_item("教学内容").ok_or_else(|| {
                anyhow::anyhow!("not_found: course content menu item 教学内容 not found")
            })?;
            let content_id = content_id_from_url(&item.url)
                .ok_or_else(|| anyhow::anyhow!("not_found: 教学内容 content_id not found"))?;
            (item.label.clone(), content_id, item.url.clone())
        };

        let mut queue = VecDeque::from([ContentProbe {
            content_id: root_content_id.clone(),
            path: vec![root_label.clone()],
        }]);
        let mut visited = HashSet::new();
        let mut items = Vec::new();

        while let Some(probe) = queue.pop_front() {
            if !visited.insert(probe.content_id.clone()) {
                continue;
            }
            let dom = self
                .client
                .bb_course_content_page(self.meta.id(), &probe.content_id)
                .await
                .with_context(|| format!("fetch content page {}", probe.content_id))?;
            let page_items = parse_content_page(&dom, self.meta.id(), &probe.path)?;
            for item in page_items {
                if item.kind == "folder" {
                    if let Some(child) = item.child_content_id.clone() {
                        if !visited.contains(&child) {
                            queue.push_back(ContentProbe {
                                content_id: child,
                                path: item.path.clone(),
                            });
                        }
                    }
                }
                items.push(item);
            }
        }

        Ok(CourseContentsTree {
            course: CourseSnapshot::from(self.meta()),
            root: CourseContentRoot {
                label: root_label,
                content_id: root_content_id,
                url: root_url,
            },
            items,
        })
    }

    pub async fn list_courseware(&self) -> anyhow::Result<CoursewareList> {
        let tree = self.get_contents_tree(None).await?;
        Ok(CoursewareList {
            course: tree.course.clone(),
            files: courseware_from_tree(self.meta.id(), &tree.items),
        })
    }

    pub async fn get_grades(&self) -> anyhow::Result<CourseGrades> {
        let item = self
            .find_menu_item("个人成绩")
            .ok_or_else(|| anyhow::anyhow!("not_found: grade menu item 个人成绩 not found"))?;
        let dom = self
            .client
            .bb_page_by_uri_follow_redirects(&item.url)
            .await
            .context("fetch my grades page")?;
        let grades = parse_grade_rows(&dom, self.meta.id())?;
        Ok(CourseGrades {
            course: CourseSnapshot::from(self.meta()),
            grades,
        })
    }
}

#[derive(Debug, Clone)]
struct ContentProbe {
    content_id: String,
    path: Vec<String>,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseSnapshot {
    pub id: String,
    pub title: String,
    pub name: String,
    pub is_current: bool,
    pub launcher_url: String,
}

impl From<&CourseMeta> for CourseSnapshot {
    fn from(meta: &CourseMeta) -> Self {
        Self {
            id: meta.id().to_owned(),
            title: meta.title().to_owned(),
            name: meta.name().to_owned(),
            is_current: meta.is_current(),
            launcher_url: meta.launcher_url().to_owned(),
        }
    }
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseContentRoot {
    pub label: String,
    pub content_id: String,
    pub url: String,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseContentsTree {
    pub course: CourseSnapshot,
    pub root: CourseContentRoot,
    pub items: Vec<CourseTreeItem>,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseTreeAttachment {
    pub id: String,
    pub name: String,
    pub url: String,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseTreeItem {
    pub id: String,
    pub stable_id: String,
    pub kind: String,
    pub title: String,
    pub path: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub child_content_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub file_url: Option<String>,
    pub attachments: Vec<CourseTreeAttachment>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub descriptions: Vec<String>,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CoursewareList {
    pub course: CourseSnapshot,
    pub files: Vec<CoursewareFile>,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CoursewareFile {
    pub id: String,
    pub course_id: String,
    pub source_item_id: String,
    pub name: String,
    pub path: Vec<String>,
    pub url: String,
    pub kind: String,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseGrades {
    pub course: CourseSnapshot,
    pub grades: Vec<CourseGrade>,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseGrade {
    pub id: String,
    pub row_id: String,
    pub item_id: String,
    pub title: String,
    pub category: String,
    pub last_activity_raw: String,
    pub activity_type: String,
    pub score: String,
    pub points_possible: String,
    pub status: String,
}

fn parse_content_page(
    dom: &scraper::Html,
    course_id: &str,
    parent_path: &[String],
) -> anyhow::Result<Vec<CourseTreeItem>> {
    let selector = Selector::parse("#content_listContainer > li, ul.contentList > li").unwrap();
    dom.select(&selector)
        .map(|li| parse_content_li(li, course_id, parent_path))
        .collect()
}

fn parse_content_li(
    li: scraper::ElementRef<'_>,
    course_id: &str,
    parent_path: &[String],
) -> anyhow::Result<CourseTreeItem> {
    let id = content_id_from_li(li).context("content item id not found")?;
    let kind = content_kind_from_li(li);
    let title = content_title_from_li(li).unwrap_or_else(|| id.clone());
    let mut path = parent_path.to_vec();
    path.push(title.clone());

    let link_selector = Selector::parse("a[href]").unwrap();
    let mut list_url = None;
    let mut child_content_id = None;
    let mut file_url = None;
    for a in li.select(&link_selector) {
        let Some(href) = a.value().attr("href") else {
            continue;
        };
        if href.contains("listContent.jsp") {
            if let Some(cid) = content_id_from_url(href) {
                child_content_id = Some(cid);
                list_url = Some(href.to_owned());
            }
        }
        if href.contains("/bbcswebdav/") && file_url.is_none() {
            file_url = Some(href.to_owned());
        }
    }
    if kind == "folder" && child_content_id.is_none() {
        child_content_id = Some(id.clone());
    }
    if kind == "folder" && list_url.is_none() {
        list_url = Some(format!(
            "/webapps/blackboard/content/listContent.jsp?course_id={course_id}&content_id={}",
            child_content_id.as_deref().unwrap_or(&id)
        ));
    }

    let attachments = parse_attachments(li, course_id, &id)?;
    let descriptions = parse_descriptions(li);

    Ok(CourseTreeItem {
        stable_id: id::course_content(course_id, &id),
        id,
        kind,
        title,
        path,
        child_content_id,
        url: list_url,
        file_url,
        attachments,
        descriptions,
    })
}

fn content_id_from_li(li: scraper::ElementRef<'_>) -> Option<String> {
    if let Some(raw) = li.value().attr("id") {
        if let Some(id) = raw.strip_prefix("contentListItem:") {
            if !id.is_empty() {
                return Some(id.to_owned());
            }
        }
        if looks_like_content_id(raw) {
            return Some(raw.to_owned());
        }
    }

    let selector = Selector::parse("[id]").unwrap();
    li.select(&selector).find_map(|el| {
        let id = el.value().attr("id")?;
        looks_like_content_id(id).then_some(id.to_owned())
    })
}

fn looks_like_content_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    if !bytes.starts_with(b"_") || !bytes.ends_with(b"_1") {
        return false;
    }
    value.chars().all(|ch| ch == '_' || ch.is_ascii_digit())
}

fn content_kind_from_li(li: scraper::ElementRef<'_>) -> String {
    let selector = Selector::parse("img.item_icon, img[alt]").unwrap();
    let alt = li
        .select(&selector)
        .find_map(|img| img.value().attr("alt"))
        .unwrap_or_default();
    match alt.trim() {
        "文件" => "file",
        "项目" => "item",
        "内容文件夹" => "folder",
        "作业" => "assignment",
        _ => "unknown",
    }
    .to_owned()
}

fn content_title_from_li(li: scraper::ElementRef<'_>) -> Option<String> {
    for selector in ["h3", "div.item h3", "div[id] h3", "a[href]"] {
        let selector = Selector::parse(selector).unwrap();
        if let Some(el) = li.select(&selector).next() {
            let text = normalize_text(&el.text().collect::<String>());
            if !text.is_empty() {
                return Some(text);
            }
        }
    }
    None
}

fn parse_attachments(
    li: scraper::ElementRef<'_>,
    course_id: &str,
    content_id: &str,
) -> anyhow::Result<Vec<CourseTreeAttachment>> {
    let selector = Selector::parse("ul.attachments > li > a[href]").unwrap();
    li.select(&selector)
        .map(|a| {
            let href = a.value().attr("href").context("attachment href missing")?;
            let name = normalize_text(&a.text().collect::<String>())
                .trim_start_matches('\u{a0}')
                .to_owned();
            Ok(CourseTreeAttachment {
                id: id::attachment(course_id, content_id, href),
                name: if name.is_empty() {
                    "attachment".to_owned()
                } else {
                    name
                },
                url: href.to_owned(),
            })
        })
        .collect()
}

fn parse_descriptions(li: scraper::ElementRef<'_>) -> Vec<String> {
    let selector = Selector::parse("div.details div.vtbegenerated > *, div.details").unwrap();
    li.select(&selector)
        .map(|el| normalize_text(&collect_text(el)))
        .filter(|text| !text.is_empty())
        .collect()
}

fn content_id_from_url(uri: &str) -> Option<String> {
    let url = low_level::convert_uri(uri).ok()?.into_url().ok()?;
    url.query_pairs()
        .find(|(key, _)| key == "content_id")
        .map(|(_, value)| value.to_string())
}

fn courseware_from_tree(course_id: &str, items: &[CourseTreeItem]) -> Vec<CoursewareFile> {
    let mut files = Vec::new();
    for item in items {
        if item.kind == "file" {
            if let Some(url) = &item.file_url {
                files.push(CoursewareFile {
                    id: id::course_content(course_id, &item.id),
                    course_id: course_id.to_owned(),
                    source_item_id: item.id.clone(),
                    name: item.title.clone(),
                    path: item.path.clone(),
                    url: url.clone(),
                    kind: "file".to_owned(),
                });
            }
        }
        for attachment in &item.attachments {
            files.push(CoursewareFile {
                id: attachment.id.clone(),
                course_id: course_id.to_owned(),
                source_item_id: item.id.clone(),
                name: attachment.name.clone(),
                path: item.path.clone(),
                url: attachment.url.clone(),
                kind: "attachment".to_owned(),
            });
        }
    }
    files
}

fn parse_grade_rows(dom: &scraper::Html, course_id: &str) -> anyhow::Result<Vec<CourseGrade>> {
    let row_selector = Selector::parse("#grades_wrapper .sortable_item_row[role='row'], .gradeTableNew .sortable_item_row[role='row'], .sortable_item_row.row").unwrap();
    let cell_selector = Selector::parse("div.cell").unwrap();
    let mut grades = Vec::new();
    for row in dom.select(&row_selector) {
        let row_id = grade_row_id(row).unwrap_or_else(|| grades.len().to_string());
        let item_id = format!("_{row_id}_1");
        let cells = row.select(&cell_selector).collect::<Vec<_>>();
        if cells.is_empty() {
            continue;
        }
        let title = grade_title(cells[0]);
        if title.is_empty() || title == "项目" {
            continue;
        }
        let category = grade_category(row).unwrap_or_default();
        let last_activity_raw = cells
            .get(1)
            .map(|cell| normalize_text(&cell.text().collect::<String>()))
            .unwrap_or_default();
        let (activity_type, last_activity_raw) = split_activity(&last_activity_raw);
        let score_raw = cells
            .get(2)
            .map(|cell| normalize_text(&cell.text().collect::<String>()))
            .unwrap_or_default();
        let (score, points_possible) = split_score(&score_raw);
        let status = cells
            .get(3)
            .map(|cell| normalize_text(&cell.text().collect::<String>()))
            .unwrap_or_default();
        grades.push(CourseGrade {
            id: id::grade(course_id, &item_id),
            row_id,
            item_id,
            title,
            category,
            last_activity_raw,
            activity_type,
            score,
            points_possible,
            status,
        });
    }
    Ok(grades)
}

fn grade_row_id(row: scraper::ElementRef<'_>) -> Option<String> {
    let raw = row.value().attr("id")?;
    raw.split(|ch: char| !ch.is_ascii_digit())
        .filter(|part| !part.is_empty())
        .max_by_key(|part| part.len())
        .map(ToOwned::to_owned)
}

fn grade_title(cell: scraper::ElementRef<'_>) -> String {
    let direct = cell
        .children()
        .filter_map(|node| match node.value() {
            scraper::node::Node::Text(text) => Some(text.to_string()),
            _ => None,
        })
        .collect::<String>();
    let direct = normalize_text(&direct);
    if !direct.is_empty() {
        return direct;
    }
    let selector = Selector::parse("a, span").unwrap();
    cell.select(&selector)
        .next()
        .map(|el| normalize_text(&el.text().collect::<String>()))
        .unwrap_or_else(|| normalize_text(&cell.text().collect::<String>()))
}

fn grade_category(row: scraper::ElementRef<'_>) -> Option<String> {
    let selector =
        Selector::parse(".gradable .category, .cell.gradable .context, .cell.gradable span")
            .unwrap();
    row.select(&selector).find_map(|el| {
        let text = normalize_text(&el.text().collect::<String>());
        (!text.is_empty()).then_some(text)
    })
}

fn split_activity(raw: &str) -> (String, String) {
    let raw = normalize_text(raw);
    for prefix in ["已评分", "已提交", "已创建", "已更新"] {
        if let Some(rest) = raw.strip_prefix(prefix) {
            return (prefix.to_owned(), rest.trim().to_owned());
        }
    }
    (String::new(), raw)
}

fn split_score(raw: &str) -> (String, String) {
    let raw = normalize_text(raw);
    if let Some((score, possible)) = raw.split_once('/') {
        (score.trim().to_owned(), possible.trim().to_owned())
    } else {
        (raw, String::new())
    }
}

pub struct CourseContentStream {
    /// 一次性发射的请求数量
    batch_size: usize,
    client: Client,
    course: Arc<CourseMeta>,
    visited_ids: HashSet<String>,
    probe_ids: Vec<String>,
}

impl CourseContentStream {
    fn new(client: Client, course: Arc<CourseMeta>, probe_ids: Vec<String>) -> Self {
        // implicitly deduplicate probe_ids
        let visited_ids = HashSet::from_iter(probe_ids);
        let probe_ids = visited_ids.iter().cloned().collect();
        Self {
            batch_size: 8,
            client,
            course,
            visited_ids,
            probe_ids,
        }
    }
    async fn try_next_batch(&mut self, ids: &[String]) -> anyhow::Result<Vec<CourseContentData>> {
        let futs = ids
            .iter()
            .map(|id| self.client.bb_course_content_page(&self.course.id, id));

        let doms = futures_util::future::join_all(futs).await;

        let mut all_contents = Vec::new();
        for dom in doms {
            let dom = dom?;
            let selector = Selector::parse("#content_listContainer > li").unwrap();
            let contents = dom
                .select(&selector)
                .filter_map(|li| {
                    CourseContentData::from_element(li)
                        .inspect_err(|e| log::warn!("CourseContentData::from_element error: {e}"))
                        .ok()
                })
                // filter out visited ids
                .filter(|data| self.visited_ids.insert(data.id.to_owned()))
                // add the rest new ids to probe_ids
                .inspect(|data| {
                    if data.has_link {
                        self.probe_ids.push(data.id.to_owned())
                    }
                });

            all_contents.extend(contents);
        }

        Ok(all_contents)
    }
    pub async fn next_batch(&mut self) -> Option<Vec<CourseContentData>> {
        let ids = self
            .probe_ids
            .split_off(self.probe_ids.len().saturating_sub(self.batch_size));
        if ids.is_empty() {
            return None;
        }
        match self.try_next_batch(&ids).await {
            Ok(r) => Some(r),
            Err(e) => {
                log::warn!("try_next_batch error {ids:?}: {e}");
                return Box::pin(self.next_batch()).await;
            }
        }
    }
}

#[derive(Debug, Clone)]
pub struct CourseContent {
    client: Client,
    course: Arc<CourseMeta>,
    data: Arc<CourseContentData>,
}

impl CourseContent {
    pub fn into_assignment_opt(self) -> Option<CourseAssignmentHandle> {
        if let CourseContentKind::Assignment = self.data.kind {
            Some(CourseAssignmentHandle {
                client: self.client,
                course: self.course,
                content: self.data,
            })
        } else {
            None
        }
    }
}

#[derive(Debug, serde::Deserialize, serde::Serialize)]
enum CourseContentKind {
    Document,
    Assignment,
    Announcement,
    Unknown,
}

#[derive(Debug, serde::Deserialize, serde::Serialize)]
pub struct CourseContentData {
    id: String,
    title: String,
    kind: CourseContentKind,
    has_link: bool,
    descriptions: Vec<String>,
    attachments: Vec<(String, String)>,
    #[serde(skip_serializing_if = "Option::is_none")]
    time: Option<String>,
}

fn normalize_text(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn collect_text(element: scraper::ElementRef) -> String {
    let mut text_content = String::new();
    for node_ref in element.children() {
        match node_ref.value() {
            scraper::node::Node::Text(text) => {
                if !text.trim().is_empty() {
                    text_content.push_str(text);
                }
            }
            scraper::node::Node::Element(el) => {
                if el.name() != "script"
                    && let Some(child_element) = scraper::ElementRef::wrap(node_ref)
                {
                    text_content.push_str(&collect_text(child_element));
                }
            }
            _ => {}
        }
    }
    text_content
}

fn normalize_compact_text(s: &str) -> String {
    s.chars().filter(|c| !c.is_whitespace()).collect()
}

fn announcement_dedup_key(title: &str, content: &str, time: &str) -> String {
    let title = normalize_compact_text(title);
    let content = normalize_compact_text(content);
    let time = normalize_compact_text(time);

    if content.is_empty() {
        format!("{title}|{time}")
    } else {
        format!("{title}|{time}|{content}")
    }
}

impl CourseContentData {
    fn from_element(el: scraper::ElementRef<'_>) -> anyhow::Result<Self> {
        anyhow::ensure!(el.value().name() == "li", "not a li element");
        let (img, title_div, detail_div) = el
            .child_elements()
            .take(3)
            .collect_tuple()
            .context("failed to collect 3 child elements")?;

        let kind = match img.attr("alt") {
            Some("作业") => CourseContentKind::Assignment,
            Some("项目") | Some("文件") => CourseContentKind::Document,
            alt => {
                log::warn!("unknown content kind: {alt:?}");
                CourseContentKind::Unknown
            }
        };

        let id = title_div
            .attr("id")
            .context("content_id not found")?
            .to_owned();

        let title = title_div.text().collect::<String>().trim().to_owned();
        let has_link = title_div
            .select(&Selector::parse("a").unwrap())
            .next()
            .is_some();

        let descriptions = detail_div
            .select(&Selector::parse("div.vtbegenerated > *").unwrap())
            .map(|p| collect_text(p).trim().to_owned())
            .collect::<Vec<_>>();

        let attachments = detail_div
            .select(&Selector::parse("ul.attachments > li > a").unwrap())
            .map(|a| {
                let text = a.text().collect::<String>();
                let href = a.value().attr("href").unwrap();
                let text = if let Some(text) = text.strip_prefix("\u{a0}") {
                    text.to_owned()
                } else {
                    text
                };
                Ok((text, href.to_owned()))
            })
            .collect::<anyhow::Result<Vec<_>>>()?;

        Ok(CourseContentData {
            id,
            title,
            kind,
            has_link,
            descriptions,
            attachments,
            time: None,
        })
    }
}

#[derive(Debug, Clone)]
pub struct CourseAssignmentHandle {
    client: Client,
    course: Arc<CourseMeta>,
    content: Arc<CourseContentData>,
}

impl CourseAssignmentHandle {
    pub fn id(&self) -> String {
        id::assignment(&self.course.id, &self.content.id)
    }

    async fn _get(&self) -> anyhow::Result<CourseAssignmentData> {
        let dom = self
            .client
            .bb_course_assignment_uploadpage(&self.course.id, &self.content.id)
            .await?;

        let deadline = dom
            .select(&Selector::parse("#assignMeta2 + div").unwrap())
            .next()
            .map(|e| {
                // replace consecutive whitespaces with a single space
                e.text()
                    .collect::<String>()
                    .split_whitespace()
                    .collect::<Vec<_>>()
                    .join(" ")
            });

        let submission = self._get_submission_summary().await?;

        Ok(CourseAssignmentData {
            deadline,
            submission,
        })
    }
    pub async fn get(&self) -> anyhow::Result<CourseAssignment> {
        let data = with_cache(
            &format!(
                "CourseAssignmentHandle::_get_{}_{}",
                self.content.id, self.course.id
            ),
            self.client.cache_ttl(),
            self._get(),
        )
        .await?;

        Ok(CourseAssignment {
            client: self.client.clone(),
            course: self.course.clone(),
            content: self.content.clone(),
            data,
        })
    }

    async fn _get_submission_summary(&self) -> anyhow::Result<CourseAssignmentSubmissionSummary> {
        let dom = self
            .client
            .bb_course_assignment_viewpage(&self.course.id, &self.content.id)
            .await?;
        Ok(parse_assignment_submission_summary(
            &dom,
            &self.course.id,
            &self.content.id,
        ))
    }
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
struct CourseAssignmentData {
    deadline: Option<String>,
    submission: CourseAssignmentSubmissionSummary,
}

#[derive(Debug, Clone, Default, serde::Deserialize, serde::Serialize)]
pub struct CourseAssignmentSubmissionSummary {
    pub submitted: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latest_attempt_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latest_attempt_label: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latest_submitted_at_raw: Option<String>,
    pub late: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub score: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub points_possible: Option<String>,
    pub submitted_file_count: usize,
    pub feedback_available: bool,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseAssignmentSubmission {
    pub submitted: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latest_attempt_id: Option<String>,
    pub attempts: Vec<CourseAssignmentAttempt>,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseAssignmentAttempt {
    pub id: String,
    pub attempt_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub index: Option<u32>,
    pub label: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub submitted_at_raw: Option<String>,
    pub late: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub score: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub points_possible: Option<String>,
    pub files: Vec<CourseAssignmentSubmittedFile>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub feedback_raw: Option<String>,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct CourseAssignmentSubmittedFile {
    pub id: String,
    pub file_id: String,
    pub attempt_id: String,
    pub name: String,
    pub url: String,
}

#[derive(Debug, Clone)]
struct AssignmentAttemptLink {
    attempt_id: String,
    index: Option<u32>,
    url: String,
    label: String,
}

fn parse_assignment_submission_summary(
    dom: &scraper::Html,
    course_id: &str,
    content_id: &str,
) -> CourseAssignmentSubmissionSummary {
    let Some(attempt) = parse_current_assignment_attempt(dom, course_id, content_id) else {
        return CourseAssignmentSubmissionSummary::default();
    };
    CourseAssignmentSubmissionSummary {
        submitted: true,
        latest_attempt_id: Some(attempt.id),
        latest_attempt_label: Some(attempt.label),
        latest_submitted_at_raw: attempt.submitted_at_raw,
        late: attempt.late,
        score: attempt.score,
        points_possible: attempt.points_possible,
        submitted_file_count: attempt.files.len(),
        feedback_available: attempt
            .feedback_raw
            .as_deref()
            .map(|s| !s.trim().is_empty())
            .unwrap_or(false),
    }
}

fn parse_current_assignment_attempt(
    dom: &scraper::Html,
    course_id: &str,
    content_id: &str,
) -> Option<CourseAssignmentAttempt> {
    let label_el = dom
        .select(&Selector::parse("h3#currentAttempt_label").unwrap())
        .next()?;
    let label = normalize_text(&label_el.text().collect::<String>());
    if label.is_empty() {
        return None;
    }

    let current_link = dom
        .select(&Selector::parse("#currentAttempt_attemptList li.current a[href], #currentAttempt_attemptList a[href]").unwrap())
        .find(|a| {
            let text = normalize_text(&a.text().collect::<String>());
            text.contains(&label) || label.contains(text.split_whitespace().next().unwrap_or(""))
        });
    let attempt_id_from_link = current_link
        .and_then(|a| a.value().attr("href"))
        .and_then(|href| query_param(href, "attempt_id"));
    let index_from_link = current_link
        .and_then(|a| a.value().attr("href"))
        .and_then(|href| query_param(href, "currentAttemptIndex"))
        .and_then(|value| value.parse::<u32>().ok());

    let mut files =
        parse_submitted_files(dom, course_id, content_id, attempt_id_from_link.as_deref());
    let attempt_id = attempt_id_from_link
        .or_else(|| files.first().map(|file| file.attempt_id.clone()))
        .unwrap_or_else(|| format!("fingerprint-{}", id::fnv1a64_hex(&label)));
    for file in &mut files {
        if file.attempt_id.starts_with("fingerprint-") {
            file.attempt_id = attempt_id.clone();
            let file_id = file.file_id.clone();
            file.id = id::assignment_submitted_file(course_id, content_id, &attempt_id, &file_id);
        }
    }

    let score = dom
        .select(&Selector::parse("#currentAttempt_grade").unwrap())
        .next()
        .and_then(|input| input.value().attr("value"))
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned);
    let points_possible = dom
        .select(&Selector::parse("#currentAttempt_pointsPossible").unwrap())
        .next()
        .map(|el| normalize_text(&el.text().collect::<String>()))
        .map(|text| text.trim_start_matches('/').trim().to_owned())
        .filter(|text| !text.is_empty());
    let feedback_raw = dom
        .select(&Selector::parse("#currentAttempt_feedback").unwrap())
        .next()
        .map(|el| normalize_text(&el.text().collect::<String>()))
        .filter(|text| !text.is_empty());

    let current_text = dom
        .select(&Selector::parse("#currentAttempt").unwrap())
        .next()
        .map(|el| normalize_text(&el.text().collect::<String>()))
        .unwrap_or_default();
    let late = label.contains("逾期") || current_text.contains("逾期");
    let submitted_at_raw = extract_attempt_time(&label);
    let index = index_from_link.or_else(|| extract_attempt_index(&label));

    Some(CourseAssignmentAttempt {
        id: id::assignment_attempt(course_id, content_id, &attempt_id),
        attempt_id,
        index,
        label,
        submitted_at_raw,
        late,
        score,
        points_possible,
        files,
        feedback_raw,
    })
}

fn parse_assignment_attempt_links(dom: &scraper::Html) -> Vec<AssignmentAttemptLink> {
    let selector = Selector::parse("#currentAttempt_attemptList a.attemptInfo[href]").unwrap();
    dom.select(&selector)
        .filter_map(|a| {
            let href = a.value().attr("href")?.to_owned();
            let attempt_id = query_param(&href, "attempt_id")?;
            let index = query_param(&href, "currentAttemptIndex").and_then(|s| s.parse().ok());
            let label = normalize_text(&a.text().collect::<String>());
            Some(AssignmentAttemptLink {
                attempt_id,
                index: index.or_else(|| extract_attempt_index(&label)),
                url: href,
                label,
            })
        })
        .collect()
}

fn parse_submitted_files(
    dom: &scraper::Html,
    course_id: &str,
    content_id: &str,
    fallback_attempt_id: Option<&str>,
) -> Vec<CourseAssignmentSubmittedFile> {
    let li_selector = Selector::parse("#currentAttempt_submissionList > li").unwrap();
    let attachment_selector = Selector::parse("a.attachment").unwrap();
    let download_selector =
        Selector::parse("a.dwnldBtn[href], a[href*='/webapps/assignment/download']").unwrap();
    let mut files = Vec::new();

    for li in dom.select(&li_selector) {
        let attachment = li.select(&attachment_selector).next();
        let download = li.select(&download_selector).next();
        let href = download
            .and_then(|a| a.value().attr("href"))
            .or_else(|| {
                attachment
                    .and_then(|a| a.value().attr("href"))
                    .filter(|href| *href != "#")
            })
            .unwrap_or("#")
            .to_owned();
        let name = attachment
            .map(|a| normalize_text(&a.text().collect::<String>()))
            .filter(|name| !name.is_empty())
            .or_else(|| query_param(&href, "fileName"))
            .unwrap_or_else(|| "submitted-file".to_owned());
        let attempt_id = query_param(&href, "attempt_id")
            .or_else(|| fallback_attempt_id.map(ToOwned::to_owned))
            .unwrap_or_else(|| format!("fingerprint-{}", id::fnv1a64_hex(&href)));
        let file_id = query_param(&href, "file_id")
            .or_else(|| {
                attachment.and_then(|a| {
                    a.value()
                        .attr("id")
                        .and_then(|id| id.rsplit_once("attemptFile_").map(|(_, v)| v.to_owned()))
                })
            })
            .unwrap_or_else(|| format!("fingerprint-{}", id::fnv1a64_hex(&href)));
        files.push(CourseAssignmentSubmittedFile {
            id: id::assignment_submitted_file(course_id, content_id, &attempt_id, &file_id),
            file_id,
            attempt_id,
            name,
            url: href,
        });
    }

    files
}

fn query_param(uri: &str, key: &str) -> Option<String> {
    let url = low_level::convert_uri(uri).ok()?.into_url().ok()?;
    url.query_pairs()
        .find(|(k, _)| k == key)
        .map(|(_, value)| value.to_string())
}

fn extract_attempt_index(label: &str) -> Option<u32> {
    let re = regex::Regex::new(r"(?:尝试|第\s*)(\d+)").unwrap();
    re.captures(label)
        .and_then(|caps| caps.get(1))
        .and_then(|m| m.as_str().parse().ok())
}

fn extract_attempt_time(label: &str) -> Option<String> {
    let re =
        regex::Regex::new(r"(\d{2,4}-\d{1,2}-\d{1,2}\s*(?:上午|下午)?\s*\d{1,2}:\d{2})").unwrap();
    re.captures(label)
        .and_then(|caps| caps.get(1))
        .map(|m| normalize_text(m.as_str()))
}

#[derive(Debug, Clone)]
pub struct CourseAssignment {
    client: Client,
    course: Arc<CourseMeta>,
    content: Arc<CourseContentData>,
    data: CourseAssignmentData,
}

impl CourseAssignment {
    pub fn title(&self) -> &str {
        &self.content.title
    }

    pub fn descriptions(&self) -> &[String] {
        &self.content.descriptions
    }

    pub fn attachments(&self) -> &[(String, String)] {
        &self.content.attachments
    }

    pub fn last_attempt(&self) -> Option<&str> {
        self.data.submission.latest_attempt_label.as_deref()
    }

    pub fn submission_summary(&self) -> &CourseAssignmentSubmissionSummary {
        &self.data.submission
    }

    pub async fn get_submission(&self) -> anyhow::Result<CourseAssignmentSubmission> {
        let dom = self
            .client
            .bb_course_assignment_viewpage(&self.course.id, &self.content.id)
            .await?;
        let current_attempt =
            parse_current_assignment_attempt(&dom, &self.course.id, &self.content.id);
        let current_attempt_id = current_attempt
            .as_ref()
            .map(|attempt| attempt.attempt_id.clone());
        let links = parse_assignment_attempt_links(&dom);
        let mut attempts = Vec::new();
        let mut seen_attempt_ids = HashSet::new();

        if links.is_empty() {
            if let Some(attempt) = current_attempt {
                seen_attempt_ids.insert(attempt.attempt_id.clone());
                attempts.push(attempt);
            }
        } else {
            for link in links {
                if current_attempt_id.as_deref() == Some(link.attempt_id.as_str()) {
                    if let Some(attempt) = current_attempt.clone() {
                        seen_attempt_ids.insert(attempt.attempt_id.clone());
                        attempts.push(attempt);
                        continue;
                    }
                }
                let attempt = match self.client.bb_page_by_uri_follow_redirects(&link.url).await {
                    Ok(attempt_dom) => parse_current_assignment_attempt(
                        &attempt_dom,
                        &self.course.id,
                        &self.content.id,
                    ),
                    Err(err) => {
                        log::warn!(
                            "failed to fetch assignment attempt {} for {}:{}: {err:#}",
                            link.attempt_id,
                            self.course.id,
                            self.content.id
                        );
                        None
                    }
                }
                .unwrap_or_else(|| CourseAssignmentAttempt {
                    id: id::assignment_attempt(&self.course.id, &self.content.id, &link.attempt_id),
                    attempt_id: link.attempt_id,
                    index: link.index,
                    label: link.label,
                    submitted_at_raw: None,
                    late: false,
                    score: None,
                    points_possible: None,
                    files: Vec::new(),
                    feedback_raw: None,
                });
                if seen_attempt_ids.insert(attempt.attempt_id.clone()) {
                    attempts.push(attempt);
                }
            }
        }

        let latest_attempt_id = current_attempt_id.map(|attempt_id| {
            id::assignment_attempt(&self.course.id, &self.content.id, &attempt_id)
        });
        Ok(CourseAssignmentSubmission {
            submitted: !attempts.is_empty(),
            latest_attempt_id,
            attempts,
        })
    }

    pub async fn get_submit_formfields(&self) -> anyhow::Result<HashMap<String, String>> {
        let dom = self
            .client
            .bb_course_assignment_uploadpage(&self.course.id, &self.content.id)
            .await?;

        let extract_field = |input: scraper::ElementRef<'_>| {
            let name = input.value().attr("name")?.to_owned();
            let value = input.value().attr("value")?.to_owned();
            Some((name, value))
        };

        let submitformfields = dom
            .select(&Selector::parse("form#uploadAssignmentFormId input").unwrap())
            .map(extract_field)
            .chain(
                dom.select(&Selector::parse("div.field input").unwrap())
                    .map(extract_field),
            )
            .flatten()
            .collect::<HashMap<_, _>>();

        Ok(submitformfields)
    }

    pub async fn submit_file(&self, path: &std::path::Path) -> anyhow::Result<()> {
        log::info!("submitting file: {}", path.display());

        let ext = path
            .extension()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        let content_type = get_mime_type(&ext);
        log::info!("content type: {content_type}");

        let filename = path
            .file_name()
            .context("file name not found")?
            .to_string_lossy()
            .to_string();

        let map = self.get_submit_formfields().await?;
        log::trace!("map: {map:#?}");

        macro_rules! add_field_from_map {
            ($body:ident, $name:expr) => {
                let $body = $body.add_field(
                    $name,
                    map.get($name)
                        .with_context(|| format!("field '{}' not found", $name))?
                        .as_bytes(),
                );
            };
        }

        let body = multipart::MultipartBuilder::new();
        add_field_from_map!(body, "attempt_id");
        add_field_from_map!(body, "blackboard.platform.security.NonceUtil.nonce");
        add_field_from_map!(body, "blackboard.platform.security.NonceUtil.nonce.ajax");
        add_field_from_map!(body, "content_id");
        add_field_from_map!(body, "course_id");
        add_field_from_map!(body, "isAjaxSubmit");
        add_field_from_map!(body, "lu_link_id");
        add_field_from_map!(body, "mode");
        add_field_from_map!(body, "recallUrl");
        add_field_from_map!(body, "remove_file_id");
        add_field_from_map!(body, "studentSubmission.text_f");
        add_field_from_map!(body, "studentSubmission.text_w");
        add_field_from_map!(body, "studentSubmission.type");
        add_field_from_map!(body, "student_commentstext_f");
        add_field_from_map!(body, "student_commentstext_w");
        add_field_from_map!(body, "student_commentstype");
        add_field_from_map!(body, "textbox_prefix");
        let body = body
            .add_field("studentSubmission.text", b"")
            .add_field("student_commentstext", b"")
            .add_field("dispatch", b"submit")
            .add_field("newFile_artifactFileId", b"undefined")
            .add_field("newFile_artifactType", b"undefined")
            .add_field("newFile_artifactTypeResourceKey", b"undefined")
            .add_field("newFile_attachmentType", b"L") // not sure
            .add_field("newFile_fileId", b"new")
            .add_field("newFile_linkTitle", filename.as_bytes())
            .add_field("newFilefilePickerLastInput", b"dummyValue")
            .add_file(
                "newFile_LocalFile0",
                &filename,
                content_type,
                std::fs::File::open(path)?,
            )
            .add_field("useless", b"");

        let res = self.client.bb_course_assignment_uploaddata(body).await?;

        if !res.status().is_success() {
            let st = res.status();
            let rbody = res.text().await?;
            if rbody.contains("尝试呈现错误页面时发生严重的内部错误") {
                anyhow::bail!("invalid status {} (caused by unknown server error)", st);
            }

            log::debug!("response: {rbody}");
            anyhow::bail!("invalid status {}", st);
        }

        Ok(())
    }

    /// Try to parse the deadline string into a NaiveDateTime.
    pub fn deadline(&self) -> Option<chrono::DateTime<chrono::Local>> {
        let d = self.data.deadline.as_deref()?;
        let re = regex::Regex::new(
            r"(\d{4})年(\d{1,2})月(\d{1,2})日 星期. (上午|下午)(\d{1,2}):(\d{1,2})",
        )
        .unwrap();

        if let Some(caps) = re.captures(d) {
            let year: i32 = caps[1].parse().ok()?;
            let month: u32 = caps[2].parse().ok()?;
            let day: u32 = caps[3].parse().ok()?;
            let mut hour: u32 = caps[5].parse().ok()?;
            let minute: u32 = caps[6].parse().ok()?;

            // Adjust for PM times
            if &caps[4] == "下午" && hour < 12 {
                hour += 12;
            }

            // Create NaiveDateTime
            let naive_dt = chrono::NaiveDateTime::new(
                chrono::NaiveDate::from_ymd_opt(year, month, day)?,
                chrono::NaiveTime::from_hms_opt(hour, minute, 0)?,
            );

            let r = chrono::Local.from_local_datetime(&naive_dt).unwrap();

            Some(r)
        } else {
            None
        }
    }

    pub fn deadline_raw(&self) -> Option<&str> {
        self.data.deadline.as_deref()
    }

    #[allow(dead_code)]
    pub async fn download_attachment(
        &self,
        uri: &str,
        dest: &std::path::Path,
    ) -> anyhow::Result<()> {
        log::debug!("downloading attachment from https://course.pku.edu.cn{uri}");
        let res = self.client.get_by_uri(uri).await?;
        anyhow::ensure!(
            res.status().as_u16() == 302,
            "status not 302: {}",
            res.status()
        );

        let loc = res
            .headers()
            .get("location")
            .context("location header not found")?
            .to_str()
            .context("location header not str")?
            .to_owned();

        log::debug!("redicted to https://course.pku.edu.cn{loc}");
        let res = self.client.get_by_uri(&loc).await?;
        anyhow::ensure!(res.status().is_success(), "status not success");

        let rbody = res.bytes().await?;
        let r = compio::fs::write(dest, rbody).await;
        compio::buf::buf_try!(@try r);
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct CourseAnnouncementHandle {
    course: Arc<CourseMeta>,
    content: Arc<CourseContentData>,
}

impl CourseAnnouncementHandle {
    pub fn id(&self) -> String {
        id::announcement(&self.course.id, &self.content.id)
    }

    pub fn title(&self) -> &str {
        &self.content.title
    }

    pub fn time(&self) -> Option<&str> {
        self.content.time.as_deref()
    }

    pub fn descriptions(&self) -> &[String] {
        &self.content.descriptions
    }

    pub fn attachments(&self) -> &[(String, String)] {
        &self.content.attachments
    }
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
pub struct CourseVideoMeta {
    title: String,
    time: String,
    url: String,
}

impl CourseVideoMeta {
    pub fn title(&self) -> &str {
        &self.title
    }
    pub fn time(&self) -> &str {
        &self.time
    }
}

#[derive(Debug)]
pub struct CourseVideoHandle {
    client: Client,
    meta: Arc<CourseVideoMeta>,
    course: Arc<CourseMeta>,
}

impl CourseVideoHandle {
    /// Stable course video identifier computed from course id and source URL fingerprint.
    pub fn id(&self) -> String {
        id::video(
            &self.course.id,
            &self.meta.title,
            &self.meta.time,
            &self.meta.url,
        )
    }
    pub fn meta(&self) -> &CourseVideoMeta {
        &self.meta
    }
    async fn get_iframe_url(&self) -> anyhow::Result<String> {
        let res = self.client.get_by_uri(&self.meta.url).await?;
        anyhow::ensure!(res.status().is_success(), "status not success");
        let rbody = res.text().await?;
        let dom = scraper::Html::parse_document(&rbody);
        let iframe = dom
            .select(&Selector::parse("#content iframe").unwrap())
            .next()
            .context("iframe not found")?;
        let src = iframe
            .value()
            .attr("src")
            .context("src not found")?
            .to_owned();

        let res = self.client.get_by_uri(&src).await?;
        anyhow::ensure!(res.status().as_u16() == 302, "status not 302");
        let loc = res
            .headers()
            .get("location")
            .context("location header not found")?
            .to_str()
            .context("location header not str")?
            .to_owned();

        Ok(loc)
    }

    async fn get_sub_info(&self, loc: &str) -> anyhow::Result<String> {
        let qs = qs::Query::from_str(loc).context("parse loc qs failed")?;
        let course_id = qs
            .get("course_id")
            .context("course_id not found")?
            .to_owned();
        let sub_id = qs.get("sub_id").context("sub_id not found")?.to_owned();
        let app_id = qs.get("app_id").context("app_id not found")?.to_owned();
        let auth_data = qs
            .get("auth_data")
            .context("auth_data not found")?
            .to_owned();

        let body = self
            .client
            .bb_course_video_sub_info(&course_id, &sub_id, &app_id, &auth_data)
            .await?;

        Ok(body)
    }

    fn get_media_path(&self, text: &str) -> anyhow::Result<MediaPath> {
        let sub = serde_json::from_str::<SubInfo>(text).context("parse sub info failed")?;

        #[derive(Debug, serde::Deserialize)]
        struct SubInfo {
            list: Vec<SubItem>,
        }

        #[derive(Debug, serde::Deserialize)]
        struct SubItem {
            sub_content: String,
        }

        #[derive(Debug, serde::Deserialize)]
        struct SubContent {
            save_playback: SavePlayback,
        }

        #[derive(Debug, serde::Deserialize)]
        struct SavePlayback {
            is_m3u8: String,
            contents: String,
        }

        let Some(item) = sub.list.first() else {
            anyhow::bail!("sub list is empty, got {}", text);
        };

        let sub_content = serde_json::from_str::<SubContent>(&item.sub_content)
            .context("parse sub content failed")?;

        let is_m3u8 = sub_content.save_playback.is_m3u8;
        let url = sub_content.save_playback.contents;

        if is_m3u8 == "yes" {
            return Ok(MediaPath::M3u8(url));
        }

        if url.ends_with(".mp4") {
            return Ok(MediaPath::Mp4(url));
        }

        anyhow::bail!("not m3u8 or mp4, got {}", item.sub_content);
    }

    async fn get_m3u8_playlist(&self, url: &str) -> anyhow::Result<bytes::Bytes> {
        let res = self.client.get_by_uri(url).await?;
        anyhow::ensure!(res.status().is_success(), "status not success");
        let rbody = res.bytes().await?;
        Ok(rbody)
    }

    async fn _get(&self) -> anyhow::Result<(String, bytes::Bytes)> {
        let loc = self.get_iframe_url().await?;
        loop {
            let info = self.get_sub_info(&loc).await?;
            let media = self.get_media_path(&info)?;
            match media {
                MediaPath::M3u8(pl_url) => {
                    let pl_raw = self.get_m3u8_playlist(&pl_url).await?;
                    break Ok((pl_url, pl_raw));
                }
                MediaPath::Mp4(url) => {
                    log::warn!("mp4 ({url}) not supported yet, try again...");
                    compio::time::sleep(std::time::Duration::from_secs(1)).await;
                }
            }
        }
    }

    #[cfg(feature = "m3u8-rs")]
    pub async fn get(&self) -> anyhow::Result<CourseVideo> {
        let (pl_url, pl_raw) = self._get().await.with_context(|| {
            format!(
                "get course video for {} {}",
                self.course.title(),
                self.meta().title()
            )
        })?;

        let pl_raw = pl_raw.to_vec();
        let (_, pl) = m3u8_rs::parse_playlist(&pl_raw)
            .map_err(|e| anyhow::anyhow!("{:#}", e))
            .context("parse m3u8 failed")?;

        match pl {
            m3u8_rs::Playlist::MasterPlaylist(_) => {
                anyhow::bail!("master playlist not supported")
            }
            m3u8_rs::Playlist::MediaPlaylist(pl) => Ok(CourseVideo {
                client: self.client.clone(),
                course: self.course.clone(),
                meta: self.meta.clone(),
                pl_url: pl_url.into_url().context("parse pl_url failed")?,
                pl_raw: pl_raw.into(),
                pl,
            }),
        }
    }
}

enum MediaPath {
    M3u8(String),
    Mp4(String),
}

#[derive(Debug)]
pub struct CourseVideo {
    client: Client,
    course: Arc<CourseMeta>,
    meta: Arc<CourseVideoMeta>,
    pl_raw: bytes::Bytes,
    pl_url: url::Url,
    #[cfg(feature = "m3u8-rs")]
    pl: m3u8_rs::MediaPlaylist,
}

impl CourseVideo {
    pub fn course_name(&self) -> &str {
        self.course.name()
    }

    pub fn meta(&self) -> &CourseVideoMeta {
        &self.meta
    }

    pub fn m3u8_raw(&self) -> bytes::Bytes {
        self.pl_raw.clone()
    }

    #[cfg(feature = "m3u8-rs")]
    pub fn len_segments(&self) -> usize {
        self.pl.segments.len()
    }

    /// Refresh the key for the given segment index. You should call this method before getting the segment data referenced by the index.
    ///
    /// The EXT-X-KEY tag specifies how to decrypt them.  It applies to every Media Segment and to every Media
    /// Initialization Section declared by an EXT-X-MAP tag that appears
    /// between it and the next EXT-X-KEY tag in the Playlist file with the
    /// same KEYFORMAT attribute (or the end of the Playlist file).
    #[cfg(feature = "m3u8-rs")]
    pub fn refresh_key<'a>(
        &'a self,
        index: usize,
        key: Option<&'a m3u8_rs::Key>,
    ) -> Option<&'a m3u8_rs::Key> {
        let seg = &self.pl.segments[index];
        fn fallback_keyformat(key: &m3u8_rs::Key) -> &str {
            key.keyformat.as_deref().unwrap_or("identity")
        }

        if let Some(newkey) = &seg.key
            && key.is_none_or(|k| fallback_keyformat(k) == fallback_keyformat(newkey))
        {
            return Some(newkey);
        }
        key
    }

    #[cfg(feature = "m3u8-rs")]
    pub fn segment(&self, index: usize) -> &m3u8_rs::MediaSegment {
        &self.pl.segments[index]
    }

    /// Fetch the segment data for the given index. If `key` is provided, the segment will be decrypted.
    #[cfg(feature = "video-download")]
    pub async fn get_segment_data<'a>(
        &'a self,
        index: usize,
        key: Option<&'a m3u8_rs::Key>,
    ) -> anyhow::Result<bytes::Bytes> {
        log::info!(
            "downloading segment {}/{} for video {}",
            index,
            self.len_segments(),
            self.meta.title()
        );

        let seg = &self.pl.segments[index];

        // fetch maybe encrypted segment data
        let seg_url: String = self.pl_url.join(&seg.uri).context("join seg url")?.into();
        let mut bytes = with_cache_bytes(
            &format!("CourseVideo::download_segment_{seg_url}"),
            self.client.download_artifact_ttl(),
            self._download_segment(&seg_url),
        )
        .await
        .context("download segment data")?;

        // decrypt it if needed
        if let Some(key) = key {
            // sequence number may be used to construct IV
            let seq = (self.pl.media_sequence as usize + index) as u128;
            bytes = self
                .decrypt_segment(key, bytes, seq)
                .await
                .context("decrypt segment data")?;
        }

        Ok(bytes)
    }

    async fn _download_segment(&self, seg_url: &str) -> anyhow::Result<bytes::Bytes> {
        let res = self.client.get_by_uri(seg_url).await?;
        anyhow::ensure!(res.status().is_success(), "status not success");

        let bytes = res.bytes().await?;
        Ok(bytes)
    }

    async fn get_aes128_key(&self, url: &str) -> anyhow::Result<[u8; 16]> {
        // fetch aes128 key from uri
        let r = with_cache_bytes(
            &format!("CourseVideo::get_aes128_uri_{url}"),
            self.client.download_artifact_ttl(),
            async {
                let r = self.client.get_by_uri(url).await?.bytes().await?;
                Ok(r)
            },
        )
        .await?
        .to_vec();

        if r.len() != 16 {
            anyhow::bail!("key length not 16: {:?}", String::from_utf8(r));
        }

        // convert to array
        let mut key = [0; 16];
        key.copy_from_slice(&r);
        Ok(key)
    }

    #[cfg(feature = "video-download")]
    async fn decrypt_segment(
        &self,
        key: &m3u8_rs::Key,
        bytes: bytes::Bytes,
        seq: u128,
    ) -> anyhow::Result<bytes::Bytes> {
        use aes::cipher::{
            BlockDecryptMut, KeyIvInit, block_padding::Pkcs7, generic_array::GenericArray,
        };
        // ref: https://datatracker.ietf.org/doc/html/rfc8216#section-4.3.2.4
        match &key.method {
            // An encryption method of AES-128 signals that Media Segments are
            // completely encrypted using [AES_128] with a 128-bit key, Cipher
            // Block Chaining, and PKCS7 padding [RFC5652].  CBC is restarted
            // on each segment boundary, using either the IV attribute value
            // or the Media Sequence Number as the IV; see Section 5.2.  The
            // URI attribute is REQUIRED for this METHOD.
            m3u8_rs::KeyMethod::AES128 => {
                let uri = key.uri.as_ref().context("key uri not found")?;
                let iv = if let Some(iv) = &key.iv {
                    let iv = iv.to_ascii_uppercase();
                    let hx = iv.strip_prefix("0x").context("iv not start with 0x")?;
                    u128::from_str_radix(hx, 16).context("parse iv failed")?
                } else {
                    seq
                }
                .to_be_bytes();

                let aes_key = self.get_aes128_key(uri).await?;

                let aes_key = GenericArray::from(aes_key);
                let iv = GenericArray::from(iv);

                let de = cbc::Decryptor::<aes::Aes128>::new(&aes_key, &iv)
                    .decrypt_padded_vec_mut::<Pkcs7>(&bytes)
                    .context("decrypt failed")?;

                Ok(de.into())
            }
            r => unimplemented!("m3u8 key: {:?}", r),
        }
    }
}

/// 根据文件扩展名返回对应的 MIME 类型
pub fn get_mime_type(extension: &str) -> &str {
    let mime_types: HashMap<&str, &str> = [
        ("html", "text/html"),
        ("htm", "text/html"),
        ("txt", "text/plain"),
        ("csv", "text/csv"),
        ("json", "application/json"),
        ("xml", "application/xml"),
        ("png", "image/png"),
        ("jpg", "image/jpeg"),
        ("jpeg", "image/jpeg"),
        ("gif", "image/gif"),
        ("bmp", "image/bmp"),
        ("webp", "image/webp"),
        ("mp3", "audio/mpeg"),
        ("wav", "audio/wav"),
        ("mp4", "video/mp4"),
        ("avi", "video/x-msvideo"),
        ("pdf", "application/pdf"),
        ("zip", "application/zip"),
        ("tar", "application/x-tar"),
        ("7z", "application/x-7z-compressed"),
        ("rar", "application/vnd.rar"),
        ("exe", "application/octet-stream"),
        ("bin", "application/octet-stream"),
    ]
    .iter()
    .cloned()
    .collect();

    mime_types
        .get(extension)
        .copied()
        .unwrap_or("application/octet-stream")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_mime_type() {
        assert_eq!(get_mime_type("html"), "text/html");
        assert_eq!(get_mime_type("png"), "image/png");
        assert_eq!(get_mime_type("mp3"), "audio/mpeg");
        assert_eq!(get_mime_type("unknown"), "application/octet-stream");
    }

    #[test]
    fn test_announcement_dedup_key_empty_content_not_collapsed() {
        let k1 = announcement_dedup_key("标题 A", "", "2026-04-04");
        let k2 = announcement_dedup_key("标题 B", "", "2026-04-04");

        assert_ne!(k1, k2);
    }

    #[test]
    fn test_announcement_dedup_key_whitespace_insensitive() {
        let k1 = announcement_dedup_key("标题 A", "正文 内容", "发布时间 10:00");
        let k2 = announcement_dedup_key("标题A", "正文内容", "发布时间10:00");

        assert_eq!(k1, k2);
    }

    #[test]
    fn test_content_item_html_parse_folder_and_file() {
        let html = scraper::Html::parse_document(
            r#"
            <ul id="content_listContainer" class="contentList">
              <li id="contentListItem:_1596833_1">
                <img class="item_icon" alt="内容文件夹" />
                <div id="_1596833_1"><h3><a href="/webapps/blackboard/content/listContent.jsp?course_id=_98194_1&amp;content_id=_1596833_1">reading materials</a></h3></div>
                <div class="details"><div class="vtbegenerated"><p>folder details</p></div></div>
              </li>
              <li id="contentListItem:_1596835_1">
                <img class="item_icon" alt="文件" />
                <div id="_1596835_1"><h3><a href="/bbcswebdav/pid-1596835-dt-content-rid-11935960_1/xid-11935960_1">w2-w4 reading Nash equilibrium.pdf</a></h3></div>
                <div class="details">
                  <ul class="attachments">
                    <li><a href="/bbcswebdav/pid-1596835-dt-content-rid-11935961_1/xid-11935961_1">&nbsp;extra.pdf</a></li>
                  </ul>
                </div>
              </li>
            </ul>
            "#,
        );
        let items = parse_content_page(&html, "_98194_1", &["教学内容".to_owned()]).unwrap();
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].kind, "folder");
        assert_eq!(items[0].stable_id, "_98194_1:_1596833_1");
        assert_eq!(items[0].child_content_id.as_deref(), Some("_1596833_1"));
        assert_eq!(items[0].path, vec!["教学内容", "reading materials"]);
        assert_eq!(items[1].kind, "file");
        assert_eq!(
            items[1].file_url.as_deref(),
            Some("/bbcswebdav/pid-1596835-dt-content-rid-11935960_1/xid-11935960_1")
        );
        assert_eq!(items[1].attachments.len(), 1);
        assert_eq!(
            items[1].attachments[0].id,
            "_98194_1:_1596835_1:attachment:11935961_1"
        );
    }

    #[test]
    fn test_folder_recursion_path_for_child_page() {
        let html = scraper::Html::parse_document(
            r#"
            <ul id="content_listContainer" class="contentList">
              <li id="contentListItem:_200_1">
                <img class="item_icon" alt="文件" />
                <div id="_200_1"><h3><a href="/bbcswebdav/pid-200-dt-content-rid-1_1/xid-1_1">nested.pdf</a></h3></div>
                <div class="details"></div>
              </li>
            </ul>
            "#,
        );
        let items = parse_content_page(
            &html,
            "_98194_1",
            &["教学内容".to_owned(), "reading materials".to_owned()],
        )
        .unwrap();
        assert_eq!(
            items[0].path,
            vec!["教学内容", "reading materials", "nested.pdf"]
        );
        let files = courseware_from_tree("_98194_1", &items);
        assert_eq!(files[0].id, "_98194_1:_200_1");
        assert_eq!(files[0].path, items[0].path);
    }

    #[test]
    fn test_grade_row_parse() {
        let html = scraper::Html::parse_document(
            r#"
            <div class="gradeTableNew" role="table">
              <div id="grades_wrapper" role="rowgroup">
                <div id="row_425326_1" class="sortable_item_row row expanded" role="row">
                  <div class="cell gradable">第四次作业 <span class="category">作业</span></div>
                  <div class="cell activity timestamp">已评分 2026-5-1 下午3:34</div>
                  <div class="cell grade">10.00 / 10</div>
                  <div class="cell gradeStatus"></div>
                </div>
              </div>
            </div>
            "#,
        );
        let grades = parse_grade_rows(&html, "_98023_1").unwrap();
        assert_eq!(grades.len(), 1);
        assert_eq!(grades[0].id, "_98023_1:_425326_1");
        assert_eq!(grades[0].row_id, "425326");
        assert_eq!(grades[0].item_id, "_425326_1");
        assert_eq!(grades[0].title, "第四次作业");
        assert_eq!(grades[0].category, "作业");
        assert_eq!(grades[0].activity_type, "已评分");
        assert_eq!(grades[0].last_activity_raw, "2026-5-1 下午3:34");
        assert_eq!(grades[0].score, "10.00");
        assert_eq!(grades[0].points_possible, "10");
    }

    #[test]
    fn test_assignment_submission_parse_current_attempt_and_file() {
        let html = scraper::Html::parse_document(
            r#"
            <div id="currentAttempt">
              <div id="currentAttempt_header">
                <h3 id="currentAttempt_label">尝试2 (逾期) 26-4-26 下午3:11</h3>
                <input id="currentAttempt_grade" name="grade" value="90.00" />
                <span id="currentAttempt_pointsPossible">/100</span>
                <div id="currentAttempt_attemptList">
                  <ul>
                    <li><a class="clearfix attemptInfo" href="/webapps/assignment/uploadAssignment?course_id=_98196_1&amp;content_id=_1601603_1&amp;mode=DEFAULT&amp;currentAttemptIndex=1&amp;attempt_id=_3409502_1"><span id="attempt__3409502_1_label">第 1 次尝试 26-3-31 上午5:40</span></a></li>
                    <li class="current"><a class="clearfix attemptInfo" href="/webapps/assignment/uploadAssignment?course_id=_98196_1&amp;content_id=_1601603_1&amp;mode=DEFAULT&amp;currentAttemptIndex=2&amp;attempt_id=_3467208_1"><span id="attempt__3467208_1_label">第 2 次尝试 26-4-26 下午3:11</span><span id="attempt__3467208_1_points">90.00</span></a></li>
                  </ul>
                </div>
              </div>
              <div id="currentAttempt_content">
                <div id="currentAttempt_submission" class="segment">
                  <h4>提交</h4>
                  <ul id="currentAttempt_submissionList" class="filesList">
                    <li><a id="currentAttempt_attemptFile_3449012_1" class="attachment genericFile" href="/webapps/assignment/download?course_id=_98196_1&amp;attempt_id=_3467208_1&amp;file_id=_3449012_1&amp;fileName=answer.zip">answer.zip</a></li>
                  </ul>
                </div>
                <div id="currentAttempt_feedback" class="comment">给学习者的反馈 26-4-30 下午2:20 Good.</div>
              </div>
            </div>
            "#,
        );
        let summary = parse_assignment_submission_summary(&html, "_98196_1", "_1601603_1");
        assert!(summary.submitted);
        assert_eq!(summary.score.as_deref(), Some("90.00"));
        assert_eq!(summary.points_possible.as_deref(), Some("100"));
        assert_eq!(summary.submitted_file_count, 1);
        assert!(summary.feedback_available);
        assert!(summary.late);
        assert_eq!(
            summary.latest_attempt_id.as_deref(),
            Some("_98196_1:_1601603_1:attempt:_3467208_1")
        );

        let links = parse_assignment_attempt_links(&html);
        assert_eq!(links.len(), 2);
        assert_eq!(links[1].attempt_id, "_3467208_1");
        assert_eq!(links[1].index, Some(2));

        let attempt = parse_current_assignment_attempt(&html, "_98196_1", "_1601603_1").unwrap();
        assert_eq!(attempt.attempt_id, "_3467208_1");
        assert_eq!(attempt.index, Some(2));
        assert_eq!(
            attempt.submitted_at_raw.as_deref(),
            Some("26-4-26 下午3:11")
        );
        assert_eq!(attempt.files.len(), 1);
        assert_eq!(attempt.files[0].file_id, "_3449012_1");
        assert_eq!(
            attempt.files[0].id,
            "_98196_1:_1601603_1:attempt:_3467208_1:file:_3449012_1"
        );
    }

    #[test]
    fn test_assignment_submission_parse_unsubmitted_page() {
        let html = scraper::Html::parse_document(
            r#"
            <form id="uploadAssignmentFormId" name="uploadAssignmentForm">
              <input type="hidden" name="course_id" value="_98023_1" />
              <input type="hidden" name="content_id" value="_1611932_1" />
            </form>
            "#,
        );
        let summary = parse_assignment_submission_summary(&html, "_98023_1", "_1611932_1");
        assert!(!summary.submitted);
        assert!(summary.latest_attempt_id.is_none());
        assert_eq!(summary.submitted_file_count, 0);
    }
}
