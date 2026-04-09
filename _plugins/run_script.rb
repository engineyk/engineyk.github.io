Jekyll::Hooks.register :site, :post_read do |site|
  script  = File.join(site.source, "gen_resources.py")
  output  = File.join(site.source, "resources.html")
  posts_dir = File.join(site.source, "_posts")

  # 获取 _posts 目录下最新文件的修改时间
  posts_mtime = Dir.glob(File.join(posts_dir, "**/*"))
                   .select { |f| File.file?(f) }
                   .map    { |f| File.mtime(f) }
                   .max || Time.at(0)

  output_mtime = File.exist?(output) ? File.mtime(output) : Time.at(0)

  # 只有 _posts 有新文件时才重新生成
  if posts_mtime > output_mtime
    puts "[Hook] _posts changed, regenerating resources.html..."
    system("python #{script}")
    system("python W:/git/Command/WinCommand/jellk/gen_resources.py")
    
  else
    puts "[Hook] resources.html is up to date, skipping."
  end
end