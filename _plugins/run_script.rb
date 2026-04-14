Jekyll::Hooks.register :site, :post_write do |site|
  script    = File.join(site.source, "gen_resources.py")
  output    = File.expand_path(File.join(site.source, "resources.html"))
  posts_dir = File.join(site.source, "_posts")

  # 需要监控的目录列表（可按需扩展）
  watch_dirs = [posts_dir]

  # 获取所有监控目录下文件的最新修改时间
  posts_mtime = watch_dirs
                   .flat_map { |dir| Dir.glob(File.join(dir, "**/*")) }
                   .select   { |f| File.file?(f) }
                   .map      { |f| File.mtime(f) }
                   .max || Time.at(0)

  # 同时检查目录本身的修改时间（捕获文件新增/删除/重命名）
  dirs_mtime = watch_dirs
                  .flat_map { |dir| Dir.glob(File.join(dir, "**/*")) }
                  .select   { |f| File.directory?(f) }
                  .map      { |f| File.mtime(f) }
                  .max || Time.at(0)

  # 也检查监控根目录自身的 mtime
  root_dirs_mtime = watch_dirs
                       .select { |d| File.directory?(d) }
                       .map    { |d| File.mtime(d) }
                       .max || Time.at(0)

  # 检查生成脚本自身是否被修改
  script_mtime = File.exist?(script) ? File.mtime(script) : Time.at(0)

  # 取所有来源中最新的修改时间
  latest_source_mtime = [posts_mtime, dirs_mtime, root_dirs_mtime, script_mtime].max

  output_mtime = File.exist?(output) ? File.mtime(output) : Time.at(0)

  # 只有源文件有变动时才重新生成
  if latest_source_mtime > output_mtime
    puts "[Hook] Source changed (latest: #{latest_source_mtime}), regenerating resources.html..."
    success = system("python #{script}")
    unless success
      Jekyll.logger.error "[Hook]", "gen_resources.py failed with exit code #{$?.exitstatus}"
    end
  else
    puts "[Hook] resources.html is up to date, skipping."
  end
end