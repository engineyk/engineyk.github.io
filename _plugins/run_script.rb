Jekyll::Hooks.register :site, :post_read do |site|
  script  = File.join(site.source, "gen_resources.py")
  output  = File.join(site.source, "resources.html")

  # 获取所有源文件的最新修改时间，排除 resources.html 自身避免循环
  all_mtime = Dir.glob(File.join(site.source, "**/*"))
                 .select { |f| File.file?(f) }
                 .reject { |f| f == output }
                 .map    { |f| File.mtime(f) }
                 .max || Time.at(0)

  output_mtime = File.exist?(output) ? File.mtime(output) : Time.at(0)

  # 只有源文件有变动时才重新生成
  if all_mtime > output_mtime
    puts "[Hook] Source files changed, regenerating resources.html..."
    system("python #{script}")
  else
    puts "[Hook] resources.html is up to date, skipping."
  end
end